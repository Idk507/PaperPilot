# HOOKS.md — Two Kinds of Hooks

This project uses hooks in two distinct senses. Don't conflate them.

1. **Dev-workflow hooks** — run on your machine/CI while you're coding (like Claude Code's
   PreToolUse/PostToolUse hooks, but for git/local dev).
2. **Runtime tool-execution hooks** — run inside the FastAPI app every time a WebMCP tool's
   backing endpoint is called. These are the ones that matter most for `SECURITY.md`.

---

## Part A — Dev-workflow hooks

### Pre-commit hook (`.git/hooks/pre-commit` or via `pre-commit` framework)

```bash
#!/usr/bin/env bash
set -e
ruff check app/
pytest tests/ -q
python -c "import app.main"  # fails fast if the app doesn't even import
echo "pre-commit checks passed"
```

Install via:
```bash
pip install pre-commit
# .pre-commit-config.yaml referencing the above checks
pre-commit install
```

### Phase-completion hook (manual, run before moving to the next phase in PHASES.md)

Not automated — a checklist the coding agent runs itself before marking a phase done:
```
1. Does the human-only path still work? (Phase 1 regression check)
2. Does every new tool have a passing manual browser test?
3. Is SECURITY.md's checklist re-verified for anything touched this phase?
4. Does ARCHITECTURE.md's tool table match the code exactly?
```

If any answer is "no," the phase is not done — this hook exists specifically to stop the
common failure mode of an AI coding agent declaring a phase finished prematurely.

---

## Part B — Runtime tool-execution hooks (the important ones)

Every WebMCP tool's backing FastAPI endpoint runs through the same pre/post hook pipeline,
implemented once in `app/services/hooks.py` and applied as a dependency, not copy-pasted
per router.

### Pipeline shape

```
Agent calls tool
   → webmcp-tools.js fetch()
      → FastAPI endpoint
         → [PRE-EXECUTE HOOKS]
              1. schema_validate(input)      # Pydantic, reject on mismatch
              2. rate_limit_check(session)    # e.g. 20 calls/min/session
              3. audit_log_start(...)         # write ToolCallLog row, outcome=pending
         → actual tool logic runs
         → [POST-EXECUTE HOOKS]
              4. sanitize_output(result)      # escape/strip before returning
              5. audit_log_finish(..., outcome)
              6. redact_pii_for_log(...)      # never persist raw doc text / full PII
   → response returned to agent
```

### Reference implementation shape

```python
# app/services/hooks.py
from fastapi import Depends, HTTPException, Request

async def pre_execute_hook(request: Request, tool_name: str, payload: dict):
    if not is_rate_limit_ok(request.session_id, tool_name):
        raise HTTPException(429, "Tool call rate limit exceeded")
    log_id = audit_log_start(request.session_id, tool_name, payload)
    return log_id

async def post_execute_hook(log_id: str, result: dict, outcome: str):
    clean_result = sanitize_output(result)
    audit_log_finish(log_id, redact_for_log(clean_result), outcome)
    return clean_result
```

Every router endpoint that backs a WebMCP tool wraps its logic with these two calls —
this is non-negotiable per `INSTRUCTIONS.md` rule #3 and #7. No tool endpoint should skip
the pipeline "just this once."

### The confirmation hook (state-mutating tools only)

For any tool in the `propose_field_values` / `extract_from_document` family, the
post-execute hook additionally enforces: **the response can only ever contain
`committed=False` rows.** There is no code path, hook or otherwise, by which a WebMCP
tool's execution can flip `committed=True`. That flip only happens in the separate
human-facing accept/reject endpoint (see `ARCHITECTURE.md` step 7-8). This is enforced at
the hook level specifically so that a future contributor adding a new tool can't
accidentally bypass it by writing directly to the DB.

### Why hooks live in one shared module, not per-router

If validation/logging/rate-limiting is duplicated across `routers/*.py`, it's only a
matter of time before one endpoint is added without it — usually the one added last,
under deadline pressure, which is exactly the one most likely to be a mutating tool. One
shared dependency-injected pipeline removes that risk category entirely.