"""Runtime tool-execution hooks.

Every WebMCP tool's backing endpoint runs through pre_execute_hook and
post_execute_hook. This module is the single place where:
  - Input is validated and rate-limited
  - Tool calls are logged to ToolCallLog
  - Output is sanitized before returning to the agent
  - PII is redacted from logs

Phase 0: placeholder implementations that are wired but do nothing heavy.
Full implementation in Phase 3 (rate limiting, audit logging).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Pre-execute hook
# ---------------------------------------------------------------------------

def pre_execute_hook(session_id: str, tool_name: str, payload: dict) -> str:
    """Validate rate limit and start an audit log row.

    Returns a log_id string that post_execute_hook uses to close the row.
    Phase 0: always allows through; returns a placeholder log_id.
    """
    log_id = f"{tool_name}-{session_id}-{datetime.now(tz=UTC).isoformat()}"
    return log_id


# ---------------------------------------------------------------------------
# Post-execute hook
# ---------------------------------------------------------------------------

def post_execute_hook(log_id: str, result: Any, outcome: str) -> Any:
    """Sanitize output and finish writing the audit log row.

    Phase 0: passes result through unchanged.
    """
    return sanitize_output(result)


# ---------------------------------------------------------------------------
# Helpers (stubs — full versions in Phase 3)
# ---------------------------------------------------------------------------

def sanitize_output(result: Any) -> Any:
    """Strip anything that could constitute a prompt injection vector.

    Full implementation in Phase 5 for document-extracted text.
    """
    return result


def redact_pii_for_log(result: Any) -> str:
    """Return a log-safe string representation of a tool result.

    Never stores raw extracted document text or full PII fields.
    """
    if isinstance(result, (dict, list)):
        return json.dumps(result)
    return str(result)[:500]
