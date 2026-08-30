"""Audit router — tool-call logging endpoint.

Route:
  POST /api/audit/log  →  write a ToolCallLog row (called by declarative form
                          submit handler in webmcp-tools.js / form templates)

This endpoint is intentionally thin — it only records agent-invoked declarative
form submissions that can't be logged through hooks.py (which covers imperative tools).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session as DbSession

from app.db import ToolCallLog, get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogIn(BaseModel):
    tool_name: str
    input_json: str = "{}"
    outcome: str = "success"


@router.post("/log", status_code=201)
async def log_tool_call(
    body: AuditLogIn,
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Log a declarative form tool call from the browser."""
    session_id = request.cookies.get("paperpilot_session")
    if not session_id:
        raise HTTPException(status_code=400, detail="No active session.")

    # Validate tool_name is a known declarative tool
    _allowed = {"submit_biz_details", "submit_fin_details"}
    if body.tool_name not in _allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown declarative tool '{body.tool_name}'.",
        )

    entry = ToolCallLog(
        session_id=session_id,
        tool_name=body.tool_name,
        input_json=body.input_json[:2000],
        output_json="{}",
        timestamp=datetime.now(tz=UTC),
        outcome=body.outcome,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {"ok": True, "log_id": entry.id}
