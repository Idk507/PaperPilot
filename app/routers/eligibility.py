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
from app.services.rules_engine import check_eligibility, flag_missing_or_risky

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

    Returns {eligible, reasons, ai_summary}.
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
        result["ai_summary"] = None
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
