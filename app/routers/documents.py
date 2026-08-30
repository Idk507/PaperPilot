"""Documents router — upload and extraction endpoints (Phase 5).

Routes
------
POST /api/documents/extract  → WebMCP extract_doc tool backing endpoint
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session as DbSession
from sqlmodel import select

from app.db import Document, get_db
from app.routers.form import (
    _apply_proposal_batch,
    _get_session_required,
)
from app.services.extraction import extract_fields
from app.services.hooks import (
    RateLimitExceeded,
    assert_same_origin,
    post_execute_hook,
    pre_execute_hook,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])

_DOC_TYPE_MAP = {
    "tax_return": "tax_return_doc",
    "bank_statement": "bank_statement_doc",
}


@router.post("/extract")
async def extract_from_document(request: Request, db: DbSession = Depends(get_db)):
    """WebMCP backing endpoint for the extract_doc tool.

    Security invariants:
    - Raw OCR text never leaves services/extraction.py
    - Only validated field values reach this endpoint
    - All extracted values are routed through _apply_proposal_batch —
      the SAME single mutation path used by propose_fields (no second path)
    - committed=False always; human must Accept before any value is saved
    - untrustedContentHint=True is set on the tool registration in JS
    """
    sess = _get_session_required(request, db)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None

    document_type = body.get("document_type") if isinstance(body, dict) else None
    if document_type not in _DOC_TYPE_MAP:
        raise HTTPException(
            status_code=422,
            detail="document_type must be 'tax_return' or 'bank_statement'.",
        )

    db_doc_type = _DOC_TYPE_MAP[document_type]

    doc = db.exec(
        select(Document).where(
            Document.session_id == sess.id,
            Document.doc_type == db_doc_type,
        )
    ).first()

    if not doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {document_type.replace('_', ' ')} has been uploaded for this session. "
                "Upload a document on Step 3 first."
            ),
        )

    assert_same_origin(request)

    try:
        log_id = pre_execute_hook(
            sess.id, "extract_doc", {"document_type": document_type}, db
        )
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    file_path = Path(doc.stored_path)
    extracted = extract_fields(file_path, document_type)

    # Route through the shared proposal batch — ONE mutation path
    proposed, skipped = _apply_proposal_batch(sess.id, extracted, "extracted_doc", db)

    result = {
        "proposed": proposed,
        "skipped": skipped,
        "message": (
            f"{len(proposed)} field(s) extracted and proposed for review."
            if proposed
            else "No recognisable field values found in this document."
        ),
    }
    post_execute_hook(log_id, result, "success", db)
    return result
