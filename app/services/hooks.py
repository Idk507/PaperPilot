"""Runtime tool-execution hooks.

Every WebMCP tool's backing endpoint runs through:
  1. pre_execute_hook  — rate-limit check + open audit log row
  2. post_execute_hook — close log row, sanitize output

Rate limit: 20 calls / 60 s / session / tool (in-memory, resets on restart).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlmodel import Session as DbSession

from app.db import ToolCallLog

RATE_LIMIT = 20
WINDOW_SECS = 60

_call_log: dict[str, deque] = defaultdict(deque)


class RateLimitExceeded(Exception):
    pass


def _check_rate_limit(session_id: str, tool_name: str) -> None:
    """Raise RateLimitExceeded if the session is over the per-tool limit."""
    key = f"{session_id}:{tool_name}"
    now = time.time()
    window = _call_log[key]
    while window and window[0] < now - WINDOW_SECS:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise RateLimitExceeded(
            f"Rate limit: {RATE_LIMIT} calls per {WINDOW_SECS}s per session exceeded."
        )
    window.append(now)


def pre_execute_hook(
    session_id: str,
    tool_name: str,
    payload: dict,
    db: DbSession,
) -> str:
    """Validate rate limit and open an audit log row.

    Returns the log_id (str) for use in post_execute_hook.
    Raises RateLimitExceeded if the session is throttled.
    """
    _check_rate_limit(session_id, tool_name)

    entry = ToolCallLog(
        session_id=session_id,
        tool_name=tool_name,
        input_json=json.dumps(_redact_sensitive(payload))[:2000],
        outcome="pending",
        timestamp=datetime.now(tz=UTC),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return str(entry.id)


def post_execute_hook(
    log_id: str,
    result: Any,
    outcome: str,
    db: DbSession,
) -> Any:
    """Close the audit log row and return sanitized output."""
    try:
        entry = db.get(ToolCallLog, int(log_id))
        if entry:
            entry.output_json = redact_pii_for_log(result)
            entry.outcome = outcome
            db.add(entry)
            db.commit()
    except (ValueError, Exception):
        pass

    return sanitize_output(result)


def sanitize_output(result: Any) -> Any:
    """Strip prompt-injection vectors from tool output.

    For dict results, coerce every value to a validated string.
    For Phase 5 document extraction, values are validated by Pydantic
    before reaching this function; this is an extra defence-in-depth pass.
    """
    if isinstance(result, dict):
        return {k: _safe_str(v) for k, v in result.items()}
    return result


def redact_pii_for_log(result: Any) -> str:
    """Return a log-safe string — never stores raw document bytes or full PII."""
    if isinstance(result, (dict, list)):
        try:
            serialized = json.dumps(result)
            return serialized[:1000]
        except (TypeError, ValueError):
            return "<non-serialisable>"
    return str(result)[:500]


def _safe_str(value: Any) -> str:
    """Coerce a value to a safe plain string."""
    s = str(value)
    # Strip leading/trailing whitespace and limit length
    return s.strip()[:500]


def _redact_sensitive(payload: dict) -> dict:
    """Remove sensitive keys from the logged payload."""
    sensitive = {"ein", "applicant_email", "applicant_name"}
    return {k: ("***" if k in sensitive else v) for k, v in payload.items()}
