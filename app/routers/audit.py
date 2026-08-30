"""Audit router — tool-call logging endpoint.

Phase 0: stub.
Full implementation in Phase 3 (wired with hooks.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.post("/log")
async def log_tool_call(request: Request):
    return {"ok": True}
