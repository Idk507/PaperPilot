"""Documents router — upload and extraction endpoints.

Phase 0: stub.
Full implementation in Phase 5.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_document():
    return {"doc_id": None, "message": "Upload not yet implemented"}


@router.post("/extract")
async def extract_from_document():
    return {"proposed": {}, "skipped": [], "message": "Extraction not yet implemented"}
