"""Form router — Phase 1-4: complete form flow + agent propose/save tools.

Routes
------
GET  /form/                  → start or resume (renders current step)
GET  /form/step/{n}          → render step n with existing values
POST /form/step/{n}          → validate + save fields, PRG redirect
GET  /form/review            → review all committed + pending fields
POST /form/submit            → finalise submission
POST /form/commit/{field}    → accept one agent proposal
POST /form/reject/{field}    → reject one agent proposal
POST /form/commit_all        → accept all proposals
POST /form/reject_all        → reject all proposals

API routes (called by WebMCP tools)
POST /api/form/propose       → agent propose uncommitted values
POST /api/form/save          → agent save-progress
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session as DbSession
from sqlmodel import select

from app.db import Document, FieldValue, FormSession, get_db
from app.services.hooks import (
    RateLimitExceeded,
    assert_same_origin,
    post_execute_hook,
    pre_execute_hook,
)
from app.services.session_utils import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    generate_csrf_token,
    verify_csrf_token,
)
from app.settings import COOKIE_SECURE, UPLOADS_DIR

router = APIRouter(prefix="/form", tags=["form"])
api_router = APIRouter(prefix="/api/form", tags=["form-api"])
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

def _prefers_json(request: Request) -> bool:
    """True when a WebMCP agent fetch() asks for JSON instead of an HTML redirect."""
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept


def _step_result(
    request: Request,
    html_fallback,
    *,
    ok: bool,
    next_url: str | None = None,
    errors: list[str] | None = None,
    message: str = "",
    next_tool_hint: str | None = None,
):
    """Return JSON for agent fetch() calls; keep HTML/redirects for humans."""
    if _prefers_json(request):
        body: dict = {"ok": ok, "message": message}
        if next_url:
            body["next"] = next_url
        if next_tool_hint:
            body["next_tool_hint"] = next_tool_hint
        if errors:
            body["errors"] = errors
        return JSONResponse(body, status_code=200 if ok else 422)
    return html_fallback


def _csrf_or_reject(request: Request, csrf_token: str, session_id: str) -> JSONResponse | None:
    if verify_csrf_token(csrf_token, session_id):
        return None
    if _prefers_json(request):
        return JSONResponse({"ok": False, "error": "Invalid CSRF token."}, status_code=403)
    raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _progress_context(session_id: str, db: DbSession) -> dict:
    """Completion % and award estimate for sidebar / review panels."""
    from app.services.rules_engine import calculate_award_estimate, get_application_checklist

    checklist = get_application_checklist(session_id, db)
    values = _load_committed_values(session_id, db)
    try:
        revenue = float(values.get("annual_revenue") or 0) or None
        drop = float(values.get("revenue_drop_pct") or 0) or None
        emp = int(float(values.get("employee_count") or 0)) or None
    except (ValueError, TypeError):
        revenue = drop = emp = None
    estimate = calculate_award_estimate(revenue, drop, emp)
    return {"checklist": checklist, "estimate": estimate}


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
            **_progress_context(sess.id, db),
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
    sess, is_new = _get_or_create_session(request, db)
    response = _render_step(request, sess, step_num, [], {}, db)
    if is_new:
        _set_session_cookie(response, sess.id)
    return response


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
    csrf_fail = _csrf_or_reject(request, csrf_token, sess.id)
    if csrf_fail:
        return csrf_fail

    data = {
        "business_name": business_name,
        "business_type": business_type,
        "year_founded": year_founded,
        "state": state,
        "ein": ein,
    }
    errors = _validate_step1(data)
    if errors:
        return _step_result(
            request,
            _render_step(request, sess, 1, errors, data, db),
            ok=False,
            errors=errors,
            message="Step 1 validation failed.",
        )

    # Save committed values
    for field, value in data.items():
        _upsert_field(sess.id, field, value.strip(), "human", True, db)

    sess.current_step = max(sess.current_step, 2)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    return _step_result(
        request,
        RedirectResponse("/form/step/2", status_code=303),
        ok=True,
        next_url="/form/step/2",
        message="Business details saved. Stay on this page and call submit_fin_details next if you have financials.",
        next_tool_hint="Call submit_fin_details next if you have financials. Do not navigate yet.",
    )


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
    csrf_fail = _csrf_or_reject(request, csrf_token, sess.id)
    if csrf_fail:
        return csrf_fail

    data = {
        "annual_revenue": annual_revenue,
        "employee_count": employee_count,
        "revenue_drop_pct": revenue_drop_pct,
        "use_of_funds": use_of_funds,
        "use_of_funds_detail": use_of_funds_detail,
    }
    errors = _validate_step2(data)
    if errors:
        return _step_result(
            request,
            _render_step(request, sess, 2, errors, data, db),
            ok=False,
            errors=errors,
            message="Step 2 validation failed.",
        )

    for field, value in data.items():
        _upsert_field(sess.id, field, value.strip(), "human", True, db)

    sess.current_step = max(sess.current_step, 3)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    return _step_result(
        request,
        RedirectResponse("/form/step/3", status_code=303),
        ok=True,
        next_url="/form/step/3",
        message="Financials saved. Stay on this page and call submit_applicant next if you have name and email.",
        next_tool_hint="Call submit_applicant next if you have name and email. Do not navigate yet.",
    )


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
    csrf_fail = _csrf_or_reject(request, csrf_token, sess.id)
    if csrf_fail:
        return csrf_fail

    data = {
        "applicant_name": applicant_name,
        "applicant_email": applicant_email,
        "certify": certify,
    }
    errors = _validate_step3(data)

    # Validate + save uploads (validation errors don't block progress)
    upload_errors = []
    for doc_type, upload_file in [
        ("tax_return_doc", tax_return_doc),
        ("bank_statement_doc", bank_statement_doc),
    ]:
        if not upload_file or not upload_file.filename:
            continue
        err = await _save_upload(upload_file, doc_type, sess.id, db)
        if err:
            upload_errors.append(err)

    all_errors = errors + upload_errors
    if all_errors:
        return _step_result(
            request,
            _render_step(request, sess, 3, all_errors, data, db),
            ok=False,
            errors=all_errors,
            message="Step 3 validation failed.",
        )

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

    return _step_result(
        request,
        RedirectResponse("/form/review", status_code=303),
        ok=True,
        next_url="/form/review",
        message="Applicant details saved. Call go_to_step with step=review only after this.",
        next_tool_hint="All sections saved. Call go_to_step with step=review only after this.",
    )


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

    # Uploaded documents (for the extract-from-doc UI)
    docs = db.exec(select(Document).where(Document.session_id == sess.id)).all()
    uploaded_docs = {d.doc_type: d.original_filename for d in docs}

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "committed_values": committed,
            "proposed_values": proposed,
            "proposed_fields": list(proposed.keys()),
            "labels": FIELD_LABELS,
            "csrf_token": generate_csrf_token(sess.id),
            "uploaded_docs": uploaded_docs,
            **_progress_context(sess.id, db),
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


# ── Proposable fields — server-side allowlist (must match webmcp-tools.js inputSchema) ──
PROPOSABLE_FIELDS: frozenset[str] = frozenset([
    "business_name", "business_type", "year_founded", "state", "ein",
    "annual_revenue", "employee_count", "revenue_drop_pct",
    "use_of_funds", "use_of_funds_detail", "applicant_name", "applicant_email",
])


def _validate_proposed_field(field_name: str, value: str) -> str | None:
    """Validate a single proposed field. Returns error string or None.

    Applies the same rules as human-typed input so agent proposals
    can never bypass validation by taking the API path.
    """
    v = value.strip()

    if field_name == "business_name":
        if not v or not (2 <= len(v) <= 200):
            return "business_name must be 2-200 characters."
    elif field_name == "business_type":
        if v not in {"sole_proprietor", "llc", "corporation", "nonprofit"}:
            return "business_type must be sole_proprietor, llc, corporation, or nonprofit."
    elif field_name == "year_founded":
        try:
            yr = int(v)
            current_yr = datetime.now(tz=UTC).year
            if not (1800 <= yr <= current_yr - 1):
                return f"year_founded must be between 1800 and {current_yr - 1}."
        except (ValueError, TypeError):
            return "year_founded must be a valid 4-digit year."
    elif field_name == "state":
        if v not in VALID_STATES:
            return "state must be a valid 2-letter US state abbreviation."
    elif field_name == "ein":
        if v and not re.match(r"^\d{2}-\d{7}$", v):
            return "ein must be in XX-XXXXXXX format or empty."
    elif field_name == "annual_revenue":
        try:
            if float(v) < 0:
                return "annual_revenue must be non-negative."
        except (ValueError, TypeError):
            return "annual_revenue must be a number."
    elif field_name == "employee_count":
        try:
            if int(float(v)) < 0:
                return "employee_count must be non-negative."
        except (ValueError, TypeError):
            return "employee_count must be a whole number."
    elif field_name == "revenue_drop_pct":
        try:
            drop = float(v)
            if not (0 <= drop <= 100):
                return "revenue_drop_pct must be between 0 and 100."
        except (ValueError, TypeError):
            return "revenue_drop_pct must be a number between 0 and 100."
    elif field_name == "use_of_funds":
        if v not in {"payroll", "rent_utilities", "equipment", "inventory", "other"}:
            return "use_of_funds must be payroll, rent_utilities, equipment, inventory, or other."
    elif field_name == "use_of_funds_detail":
        if len(v) > 500:
            return "use_of_funds_detail must be 500 characters or fewer."
    elif field_name == "applicant_name":
        if not v or len(v) > 200:
            return "applicant_name must be 1-200 characters."
    elif field_name == "applicant_email":
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.lower()):
            return "applicant_email must be a valid email address."
    return None


# ── Shared proposal-batch helper (ONE mutation path for propose + extract) ────

def _apply_proposal_batch(
    session_id: str,
    fields: dict,
    source: str,
    db: DbSession,
) -> tuple[list[str], list[dict]]:
    """Validate and upsert a batch of proposed field values.

    This is the single mutation path shared by propose_fields and extract_doc
    (see ARCHITECTURE.md §Tool design). Only fields in PROPOSABLE_FIELDS that
    pass _validate_proposed_field() are written.  committed is always False.
    """
    proposed: list[str] = []
    skipped: list[dict] = []

    for raw_field, raw_value in fields.items():
        if raw_field not in PROPOSABLE_FIELDS:
            skipped.append({"field": raw_field, "reason": "Unknown or non-proposable field."})
            continue

        str_value = str(raw_value).strip()
        err = _validate_proposed_field(raw_field, str_value)
        if err:
            skipped.append({"field": raw_field, "reason": err})
            continue

        _upsert_field(session_id, raw_field, str_value, source, False, db)
        proposed.append(raw_field)

    db.commit()
    return proposed, skipped


# ── API: agent propose values ─────────────────────────────────────────────────

@api_router.post("/propose")
async def api_propose(request: Request, db: DbSession = Depends(get_db)):
    """WebMCP backing endpoint for propose_fields tool.

    Validates each field name against the explicit allowlist and each value
    through the same validators used for human input.
    Writes FieldValue rows with committed=False, source='agent_proposed'.
    NEVER writes committed=True rows — enforced here and in hooks.py.
    """
    sess = _get_session_required(request, db)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object of {field_name: value}.")

    assert_same_origin(request)

    try:
        log_id = pre_execute_hook(sess.id, "propose_fields", body, db)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    proposed, skipped = _apply_proposal_batch(sess.id, body, "agent_proposed", db)

    result = {
        "proposed": proposed,
        "skipped": skipped,
        "message": f"{len(proposed)} field(s) proposed for review.",
    }
    post_execute_hook(log_id, result, "success", db)
    return result


# ── API: agent save progress ──────────────────────────────────────────────────

@api_router.post("/save")
async def api_save(request: Request, db: DbSession = Depends(get_db)):
    """WebMCP backing endpoint for save_progress tool."""
    sess = _get_session_required(request, db)
    assert_same_origin(request)

    try:
        log_id = pre_execute_hook(sess.id, "save_progress", {}, db)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    result = {"ok": True, "message": "Progress saved."}
    post_execute_hook(log_id, result, "success", db)
    return result


_STEP_FIELDS = {
    1: ("business_name", "business_type", "year_founded", "state", "ein"),
    2: ("annual_revenue", "employee_count", "revenue_drop_pct", "use_of_funds", "use_of_funds_detail"),
    3: ("applicant_name", "applicant_email", "certify"),
}

@api_router.post("/submit-step/{step_num}")
async def api_submit_step(
    step_num: int,
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Commit a step from JSON so submit_* tools work on every page, not only the form URL."""
    if step_num not in _STEP_FIELDS:
        raise HTTPException(status_code=404, detail="Invalid step.")

    sess = _get_session_required(request, db)
    assert_same_origin(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object.")

    data = {k: str(body.get(k, "") or "").strip() for k in _STEP_FIELDS[step_num]}
    if step_num == 1:
        errors = _validate_step1(data)
    elif step_num == 2:
        errors = _validate_step2(data)
    else:
        errors = _validate_step3(data)

    if errors:
        return JSONResponse({"ok": False, "errors": errors, "message": f"Step {step_num} validation failed."}, 422)

    try:
        log_id = pre_execute_hook(sess.id, f"submit_step_{step_num}", data, db)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    for field, value in data.items():
        if step_num == 3 and field == "certify":
            value = "true"
        if step_num == 3 and field == "applicant_email":
            value = value.lower()
        _upsert_field(sess.id, field, value, "agent_submitted", True, db)

    if step_num == 3:
        sess.status = "review"
    else:
        sess.current_step = max(sess.current_step, step_num + 1)
    sess.updated_at = datetime.now(tz=UTC)
    db.add(sess)
    db.commit()

    next_hint = {
        1: "Call submit_fin_details next if you have financials. Do not navigate yet.",
        2: "Call submit_applicant next if you have name and email. Do not navigate yet.",
        3: "All sections saved. The review page will open in a few seconds.",
    }[step_num]
    stay = " Stay on this page and call the next save tool."
    result = {
        "ok": True,
        "saved": True,
        "next_tool_hint": next_hint,
        "message": (
            f"Section {step_num} saved. The review page will open shortly."
            if step_num == 3
            else f"Section {step_num} saved.{stay}"
        ),
    }
    post_execute_hook(log_id, result, "success", db)
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_session_cookie(response, session_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=COOKIE_MAX_AGE,
    )


def _redirect_to_review(sess: FormSession, is_new: bool) -> RedirectResponse:
    resp = RedirectResponse("/form/review", status_code=303)
    if is_new:
        _set_session_cookie(resp, sess.id)
    return resp
