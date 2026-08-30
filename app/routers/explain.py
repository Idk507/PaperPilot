"""Explain router — plain-language field explanations.

Phase 0: stub.
Full implementation in Phase 3.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/explain", tags=["explain"])


@router.get("/{field_name}")
async def explain_field(field_name: str):
    return {
        "field_name": field_name,
        "label": field_name,
        "explanation": "Explanation coming in Phase 3.",
        "example": "",
    }
