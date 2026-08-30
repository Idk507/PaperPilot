"""Rules engine — pure Python eligibility logic, no FastAPI imports.

Phase 0: placeholder returning None/empty.
Full implementation in Phase 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


def check_eligibility(session_id: str, db: DBSession) -> dict:
    """Return pass/fail and reasons for the given application session."""
    return {"eligible": None, "reasons": []}


def flag_missing_or_risky(session_id: str, db: DBSession) -> dict:
    """Return a list of fields that are empty, inconsistent, or risky."""
    return {"flags": []}
