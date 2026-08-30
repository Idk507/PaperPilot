"""Form router — Phase 1: complete human-only form flow.

Routes
------
GET  /form/                  → start or resume (renders current step)
GET  /form/step/{n}          → render step n with existing values
POST /form/step/{n}          → validate + save fields, PRG redirect
GET  /form/review            → review all committed + pending fields
POST /form/submit            → finalise submission
POST /form/commit/{field}    → accept one agent proposal    (Phase 4)
POST /form/reject/{field}    → reject one agent proposal    (Phase 4)
POST /form/commit_all        → accept all proposals         (Phase 4)
POST /form/reject_all        → reject all proposals         (Phase 4)

API routes (used by WebMCP tools and declarative form auditing)
POST /api/form/propose       → agent propose values          (Phase 4)
POST /api/form/save          → agent save-progress           (Phase 4)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session as DbSession
from sqlmodel import select

from app.db import Document, FieldValue, FormSession, get_db
from app.services.session_utils import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    generate_csrf_token,
    verify_csrf_token,
)
from app.settings import UPLOADS_DIR

router = APIRouter(prefix="/form", tags=["form"])
templates = Jinja2Templates(directory="app/templates")

# ── Human-readable labels used in review.html ───────────────────────────────
FIELD_LABELS: dict[str, str] = {
    "business_name": "Business Legal Name",
    "business_type": "Business Type",
    "year_founded": "Year Founded",
    "state": "State",
    "ein": "EIN",
    "annual_revenue": "Annual Revenue (USD)",
    "employee_count": "Full-Time Employees",
    "revenue_drop_pct": "Revenue Drop (%)",
    "use_of_funds": "Primary Use of Funds",
    "use_of_funds_detail": "Use of Funds Detail",
    "tax_return_doc": "Tax Return",
    "bank_statement_doc": "Bank Statement",
    "applicant_name": "Applicant Name",
    "applicant_email": "Applicant Email",
    "certify": "Certification",
}

VALID_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]

ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_create_session(
    request: Request, db: DbSession
) -> tuple[FormSession, bool]:
    """Return (session, is_new). Creates a new session when cookie is absent."""
    sid = request.cookies.get(COOKIE_NAME)
    if sid:
        sess = db.get(FormSession, sid)
        if sess:
            return sess, False
    sess = FormSession()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess, True


def _get_session_required(request: Request, db: DbSession) -> FormSession:
    """Return the session or raise 400 if cookie is missing/invalid."""
    sid = request.cookies.get(COOKIE_NAME)
    if not sid:
        raise HTTPException(status_code=400, detail="No active session.")
    sess = db.get(FormSession, sid)
    if not sess:
        raise HTTPException(status_code=400, detail="Session not found.")
    return sess


def _load_committed_values(session_id: str, db: DbSession) -> dict[str, str]:
    rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == session_id,
            FieldValue.committed == True,
        )
    ).all()
    return {r.field_name: r.value for r in rows}


def _load_proposed_values(session_id: str, db: DbSession) -> dict[str, str]:
    rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == session_id,
            FieldValue.committed == False,
        )
    ).all()
    return {r.field_name: r.value for r in rows}


def _upsert_field(
    session_id: str,
    field_name: str,
    value: str,
    source: str,
    committed: bool,
    db: DbSession,
) -> None:
    """Insert or update a FieldValue row (upsert by session+field+committed)."""
    existing = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == session_id,
            FieldValue.field_name == field_name,
            FieldValue.committed == committed,
        )
    ).first()
    if existing:
        existing.value = value
        existing.source = source
        existing.updated_at = datetime.now(tz=UTC)
        db.add(existing)
    else:
        db.add(
            FieldValue(
                session_id=session_id,
                field_name=field_name,
                value=value,
                source=source,
                committed=committed,
            )
        )


def _render_step(
    request: Request,
    sess: FormSession,
    step: int,
    errors: list[str],
    submitted: dict[str, str],
    db: DbSession,
):
    """Render a step template. submitted values override DB values on error."""
    saved = _load_committed_values(sess.id, db)
    values = {**saved, **submitted}  # submitted takes precedence (re-fill on error)
    uploads = {}
    if step == 3:
        docs = db.exec(
            select(Document).where(Document.session_id == sess.id)
        ).all()
        uploads = {d.doc_type: d.original_filename for d in docs}

    return templates.TemplateResponse(
        request,
        f"form_step_{step}.html",
        {
            "values": values,
            "errors": errors,
            "csrf_token": generate_csrf_token(sess.id),
            "uploads": uploads,
        },
    )


# ── Step validation ───────────────────────────────────────────────────────────

def _validate_step1(data: dict) -> list[str]:
    errors: list[str] = []
    name = data.get("business_name", "").strip()
    if not name:
        errors.append("Business name is required.")
    elif len(name) < 2 or len(name) > 200:
        errors.append("Business name must be 2-200 characters.")

    if data.get("business_type") not in ["sole_proprietor", "llc", "corporation", "nonprofit"]:
        errors.append("Please select a valid business type.")

    try:
        yr = int(data.get("year_founded", ""))
        current_yr = datetime.now(tz=UTC).year
        if yr < 1800 or yr > current_yr - 1:
            errors.append(f"Year founded must be between 1800 and {current_yr - 1}.")
    except (ValueError, TypeError):
        errors.append("Year founded must be a valid 4-digit year.")

    if data.get("state") not in VALID_STATES:
        errors.append("Please select a valid US state.")

    ein = data.get("ein", "").strip()
    if ein and not re.match(r"^\d{2}-\d{7}$", ein):
        errors.append("EIN must be in format 12-3456789.")

    return errors


def _validate_step2(data: dict) -> list[str]:
    errors: list[str] = []
    try:
        rev = float(data.get("annual_revenue", ""))
        if rev < 0:
            errors.append("Annual revenue cannot be negative.")
    except (ValueError, TypeError):
        errors.append("Annual revenue must be a number.")

    try:
        emp = int(data.get("employee_count", ""))
        if emp < 0:
            errors.append("Employee count cannot be negative.")
    except (ValueError, TypeError):
        errors.append("Employee count must be a whole number.")

    try:
        drop = float(data.get("revenue_drop_pct", ""))
        if not (0 <= drop <= 100):
            errors.append("Revenue drop must be between 0% and 100%.")
    except (ValueError, TypeError):
        errors.append("Revenue drop must be a number between 0 and 100.")

    valid_funds = ["payroll", "rent_utilities", "equipment", "inventory", "other"]
    if data.get("use_of_funds") not in valid_funds:
        errors.append("Please select a primary use of funds.")
    elif data["use_of_funds"] == "other":
        detail = data.get("use_of_funds_detail", "").strip()
        if not detail:
            errors.append("Please describe the use of funds when selecting 'Other'.")
        elif len(detail) > 500:
            errors.append("Use of funds description must be 500 characters or fewer.")

    return errors


def _validate_step3(data: dict) -> list[str]:
    errors: list[str] = []
    name = data.get("applicant_name", "").strip()
    if not name:
        errors.append("Applicant full name is required.")
    elif len(name) > 200:
        errors.append("Name must be 200 characters or fewer.")

    email = data.get("applicant_email", "").strip().lower()
    if not email:
        errors.append("Email address is required.")
    elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        errors.append("Please enter a valid email address.")

    if not data.get("certify"):
        errors.append("You must certify that your information is accurate.")

    return errors


# ── GET / ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def form_index(request: Request, db: DbSession = Depends(get_db)):
    sess, is_new = _get_or_create_session(request, db)

    # If submitted, send to thank-you
    if sess.status == "submitted":
        values = _load_committed_values(sess.id, db)
        resp = templates.TemplateResponse(
            request, "thank_you.html",
            {
                "applicant_name": values.get("applicant_name", "Applicant"),
                "session_id": sess.id,
            },
        )
        if is_new:
            _set_session_cookie(resp, sess.id)
        return resp

    step = sess.current_step if sess.status == "in_progress" else 3

    if sess.status == "review":
        return _redirect_to_review(sess, is_new)

    response = _render_step(request, sess, step, [], {}, db)
    if is_new:
        _set_session_cookie(response, sess.id)
    return response


@router.get("/step/{step_num}", response_class=HTMLResponse)
async def form_step_get(
    step_num: int,
    request: Request,
    db: DbSession = Depends(get_db),
):
    if step_num not in (1, 2, 3):
        raise HTTPException(status_code=404, detail="Invalid step.")
    sess = _get_session_required(request, db)
    return _render_step(request, sess, step_num, [], {}, db)


# ── POST step/1 ───────────────────────────────────────────────────────────────

@router.post("/step/1", response_class=HTMLResponse)
async def form_step1_post(
    request: Request,
    db: DbSession = Depends(get_db),
    business_name: str = Form(default=""),
    business_type: str = Form(default=""),
    year_founded: str = Form(default=""),
    state: str = Form(default=""),
    ein: str = Form(default=""),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)

    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    data = {
        "business_name": business_name,
        "business_type": business_type,
        "year_founded": year_founded,
        "state": state,
        "ein": ein,
    }
    errors = _validate_step1(data)
    if errors:
        return _render_step(request, sess, 1, errors, data, db)

    # Save committed values
    for field, value in data.items():
        _upsert_field(sess.id, field, value.strip(), "human", True, db)

    sess.current_step = max(sess.current_step, 2)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    return RedirectResponse("/form/step/2", status_code=303)


# ── POST step/2 ───────────────────────────────────────────────────────────────

@router.post("/step/2", response_class=HTMLResponse)
async def form_step2_post(
    request: Request,
    db: DbSession = Depends(get_db),
    annual_revenue: str = Form(default=""),
    employee_count: str = Form(default=""),
    revenue_drop_pct: str = Form(default=""),
    use_of_funds: str = Form(default=""),
    use_of_funds_detail: str = Form(default=""),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)

    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    data = {
        "annual_revenue": annual_revenue,
        "employee_count": employee_count,
        "revenue_drop_pct": revenue_drop_pct,
        "use_of_funds": use_of_funds,
        "use_of_funds_detail": use_of_funds_detail,
    }
    errors = _validate_step2(data)
    if errors:
        return _render_step(request, sess, 2, errors, data, db)

    for field, value in data.items():
        _upsert_field(sess.id, field, value.strip(), "human", True, db)

    sess.current_step = max(sess.current_step, 3)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    return RedirectResponse("/form/step/3", status_code=303)


# ── POST step/3 ───────────────────────────────────────────────────────────────

@router.post("/step/3", response_class=HTMLResponse)
async def form_step3_post(
    request: Request,
    db: DbSession = Depends(get_db),
    applicant_name: str = Form(default=""),
    applicant_email: str = Form(default=""),
    certify: str = Form(default=""),
    csrf_token: str = Form(default=""),
    tax_return_doc: UploadFile | None = None,
    bank_statement_doc: UploadFile | None = None,
):
    sess = _get_session_required(request, db)

    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    data = {
        "applicant_name": applicant_name,
        "applicant_email": applicant_email,
        "certify": certify,
    }
    errors = _validate_step3(data)

    # Validate + save uploads (validation errors don't block progress)
    upload_errors = []
    for doc_type, upload_file in [
        ("tax_return", tax_return_doc),
        ("bank_statement", bank_statement_doc),
    ]:
        if not upload_file or not upload_file.filename:
            continue
        err = await _save_upload(upload_file, doc_type, sess.id, db)
        if err:
            upload_errors.append(err)

    all_errors = errors + upload_errors
    if all_errors:
        return _render_step(request, sess, 3, all_errors, data, db)

    for field, value in [
        ("applicant_name", applicant_name.strip()),
        ("applicant_email", applicant_email.strip().lower()),
        ("certify", "true"),
    ]:
        _upsert_field(sess.id, field, value, "human", True, db)

    sess.status = "review"
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    return RedirectResponse("/form/review", status_code=303)


async def _save_upload(
    upload: UploadFile,
    doc_type: str,
    session_id: str,
    db: DbSession,
) -> str | None:
    """Validate and save an uploaded file. Returns an error string or None."""
    content_type = (upload.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_MIME:
        return f"{doc_type.replace('_', ' ').title()}: unsupported file type ({content_type}). Use PDF, PNG, or JPG."

    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return f"{doc_type.replace('_', ' ').title()}: file too large (max 10 MB)."

    dest_dir = UPLOADS_DIR / session_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{doc_type}_{upload.filename}"
    dest_path.write_bytes(data)

    # Upsert Document row
    existing = db.exec(
        select(Document).where(
            Document.session_id == session_id,
            Document.doc_type == doc_type,
        )
    ).first()
    if existing:
        existing.original_filename = upload.filename or ""
        existing.stored_path = str(dest_path)
        db.add(existing)
    else:
        db.add(Document(
            session_id=session_id,
            doc_type=doc_type,
            original_filename=upload.filename or "",
            stored_path=str(dest_path),
        ))
    return None


# ── GET /form/review ──────────────────────────────────────────────────────────

@router.get("/review", response_class=HTMLResponse)
async def form_review(request: Request, db: DbSession = Depends(get_db)):
    sess = _get_session_required(request, db)
    if sess.status == "submitted":
        return RedirectResponse("/form/", status_code=303)

    committed = _load_committed_values(sess.id, db)
    proposed = _load_proposed_values(sess.id, db)

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "committed_values": committed,
            "proposed_values": proposed,
            "proposed_fields": list(proposed.keys()),
            "labels": FIELD_LABELS,
            "csrf_token": generate_csrf_token(sess.id),
        },
    )


# ── POST /form/submit ─────────────────────────────────────────────────────────

@router.post("/submit", response_class=HTMLResponse)
async def form_submit(
    request: Request,
    db: DbSession = Depends(get_db),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)

    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    if sess.status == "submitted":
        raise HTTPException(status_code=400, detail="Application already submitted.")

    # Block submission if there are pending agent proposals
    proposed = _load_proposed_values(sess.id, db)
    if proposed:
        raise HTTPException(
            status_code=400,
            detail="Please resolve all agent proposals before submitting.",
        )

    sess.status = "submitted"
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    values = _load_committed_values(sess.id, db)
    return templates.TemplateResponse(
        request,
        "thank_you.html",
        {
            "applicant_name": values.get("applicant_name", "Applicant"),
            "session_id": sess.id,
        },
    )


# ── Phase 4 stubs: commit / reject agent proposals ────────────────────────────

@router.post("/commit/{field_name}", response_class=HTMLResponse)
async def commit_field(
    field_name: str,
    request: Request,
    db: DbSession = Depends(get_db),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)
    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    proposed = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == sess.id,
            FieldValue.field_name == field_name,
            FieldValue.committed == False,
        )
    ).first()
    if proposed:
        proposed.committed = True
        proposed.updated_at = datetime.now(tz=UTC)
        db.add(proposed)
        db.commit()

    return RedirectResponse("/form/review", status_code=303)


@router.post("/reject/{field_name}", response_class=HTMLResponse)
async def reject_field(
    field_name: str,
    request: Request,
    db: DbSession = Depends(get_db),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)
    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    proposed = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == sess.id,
            FieldValue.field_name == field_name,
            FieldValue.committed == False,
        )
    ).first()
    if proposed:
        db.delete(proposed)
        db.commit()

    return RedirectResponse("/form/review", status_code=303)


@router.post("/commit_all", response_class=HTMLResponse)
async def commit_all(
    request: Request,
    db: DbSession = Depends(get_db),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)
    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    proposed_rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == sess.id,
            FieldValue.committed == False,
        )
    ).all()
    for row in proposed_rows:
        row.committed = True
        row.updated_at = datetime.now(tz=UTC)
        db.add(row)
    db.commit()
    return RedirectResponse("/form/review", status_code=303)


@router.post("/reject_all", response_class=HTMLResponse)
async def reject_all(
    request: Request,
    db: DbSession = Depends(get_db),
    csrf_token: str = Form(default=""),
):
    sess = _get_session_required(request, db)
    if not verify_csrf_token(csrf_token, sess.id):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    proposed_rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == sess.id,
            FieldValue.committed == False,
        )
    ).all()
    for row in proposed_rows:
        db.delete(row)
    db.commit()
    return RedirectResponse("/form/review", status_code=303)


# ── API: agent propose + save (Phase 4 full impl, stubs for now) ─────────────

@router.post("/api/form/propose")
async def api_propose(request: Request, db: DbSession = Depends(get_db)):
    """WebMCP tool backing endpoint for propose_fields. Phase 4 full impl."""
    _get_session_required(request, db)
    return {"proposed": [], "message": "Proposal endpoint — full implementation in Phase 4."}


@router.post("/api/form/save")
async def api_save(request: Request, db: DbSession = Depends(get_db)):
    """WebMCP tool backing endpoint for save_progress."""
    sess = _get_session_required(request, db)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()
    return {"ok": True, "message": "Progress saved."}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_session_cookie(response, session_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
    )


def _redirect_to_review(sess: FormSession, is_new: bool) -> RedirectResponse:
    resp = RedirectResponse("/form/review", status_code=303)
    if is_new:
        _set_session_cookie(resp, sess.id)
    return resp
