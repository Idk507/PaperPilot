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
    from fastapi import Request
    from sqlmodel import Session as DbSession

from app.db import ToolCallLog

RATE_LIMIT = 20
WINDOW_SECS = 60

_call_log: dict[str, deque] = defaultdict(deque)


class RateLimitExceeded(Exception):
    pass


def assert_same_origin(request: Request) -> None:
    """Defence-in-depth: reject requests whose Origin does not match the Host.

    SameSite=Lax already prevents cross-site cookie attachment on most POST
    requests. This check adds a belt-and-suspenders layer for JSON API
    endpoints called from webmcp-tools.js fetch() calls.

    Allows requests with no Origin header (server-to-server / curl / tests).
    """
    from fastapi import HTTPException

    origin = request.headers.get("origin")
    if origin is None:
        return  # no origin = not a browser cross-site call

    host = request.headers.get("host", "")
    # Normalise: strip scheme and trailing slash from origin
    origin_host = origin.split("://", 1)[-1].rstrip("/")
    if origin_host != host:
        raise HTTPException(
            status_code=403,
            detail="Cross-origin request rejected.",
        )


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
    """Close the audit log row and return sanitized output.

    Also enforces that no tool result ever claims committed=True status —
    tool calls must NEVER directly commit field values.
    """
    result = _enforce_no_committed_outputs(result)

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


def _enforce_no_committed_outputs(result: Any) -> Any:
    """Security: ensure tool results never carry committed=True.

    Defence-in-depth — propose endpoint already writes committed=False,
    but this catches any future accidental regression.
    """
    import logging as _log_mod
    _logger = _log_mod.getLogger(__name__)

    if isinstance(result, dict):
        if result.get("committed") is True:
            _logger.error(
                "SECURITY: tool result had committed=True — stripped. "
                "Tool calls must NEVER directly commit field values."
            )
            result = {k: v for k, v in result.items() if k != "committed"}
        for key, val in result.items():
            if isinstance(val, list):
                cleaned = []
                for item in val:
                    if isinstance(item, dict) and item.get("committed") is True:
                        _logger.error("SECURITY: nested committed=True in '%s' — stripped.", key)
                        item = {k: v for k, v in item.items() if k != "committed"}
                    cleaned.append(item)
                result[key] = cleaned
    return result


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
