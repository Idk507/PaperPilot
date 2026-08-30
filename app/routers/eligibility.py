"""Eligibility router — rules engine endpoints.

Routes:
  POST /api/eligibility/check  → run eligibility rules for current session
  GET  /api/eligibility/flags  → list empty / inconsistent / risky fields
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session as DbSession

from app.db import get_db
from app.services.hooks import RateLimitExceeded, post_execute_hook, pre_execute_hook
from app.services.rules_engine import (
    calculate_award_estimate,
    check_eligibility,
    flag_missing_or_risky,
    get_application_checklist,
)

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


def _require_session(request: Request) -> str:
    sid = request.cookies.get("paperpilot_session")
    if not sid:
        raise HTTPException(status_code=400, detail="No active session.")
    return sid


@router.post("/check")
async def eligibility_check(
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Run eligibility rules against the current session.

    Returns {eligible, reasons}.
    All calls are logged to ToolCallLog via pre/post hooks.
    """
    session_id = _require_session(request)

    try:
        log_id = pre_execute_hook(session_id, "check_eligibility", {}, db)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    result = check_eligibility(session_id, db)
    post_execute_hook(log_id, result, "success", db)

    # Truncate output to ≤1500 chars as per spec guidance
    output = json.dumps(result)
    if len(output) > 1500:
        result["reasons"] = result["reasons"][:10]

    return result


@router.get("/flags")
async def eligibility_flags(
    request: Request,
    db: DbSession = Depends(get_db),
):
    """List empty, inconsistent, or risky fields in the current session."""
    session_id = _require_session(request)

    try:
        log_id = pre_execute_hook(session_id, "flag_issues", {}, db)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    result = flag_missing_or_risky(session_id, db)
    post_execute_hook(log_id, result, "success", db)
    return result


@router.get("/estimate")
async def award_estimate(
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Return a tiered award estimate for the current session."""
    session_id = _require_session(request)
    from sqlmodel import select
    from app.db import FieldValue
    rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == session_id,
            FieldValue.committed == True,
        )
    ).all()
    values = {r.field_name: r.value for r in rows}
    try:
        revenue = float(values["annual_revenue"])
    except (KeyError, ValueError):
        revenue = None
    try:
        drop = float(values["revenue_drop_pct"])
    except (KeyError, ValueError):
        drop = None
    try:
        emp = int(float(values["employee_count"]))
    except (KeyError, ValueError):
        emp = None
    return calculate_award_estimate(revenue, drop, emp)


@router.get("/checklist")
async def application_checklist(
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Return a structured checklist of required fields and completion status."""
    session_id = _require_session(request)
    return get_application_checklist(session_id, db)


@router.post("/screen")
async def quick_screen(request: Request):
    """Quick eligibility pre-screen — no session required.

    Body: { annual_revenue, revenue_drop_pct, employee_count }
    Returns estimate + eligible bool. Used by home-page screener widget.
    """
    body = await request.json()
    try:
        revenue = float(body.get("annual_revenue", 0))
        drop    = float(body.get("revenue_drop_pct", 0))
        emp     = int(float(body.get("employee_count", 0)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Provide numeric annual_revenue, revenue_drop_pct, employee_count.")
    return calculate_award_estimate(revenue, drop, emp)
