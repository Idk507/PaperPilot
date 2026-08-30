"""Eligibility router — rules engine endpoints.

Phase 0: stub.
Full implementation in Phase 3.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/eligibility", tags=["eligibility"])


@router.post("/check")
async def check_eligibility():
    return {"eligible": None, "reasons": []}


@router.get("/flags")
async def get_flags():
    return {"flags": []}
