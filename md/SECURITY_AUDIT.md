# SECURITY_AUDIT.md — Phase 6 Evidence Trail

Generated: 2026-08-30. All automated checks pass: **96/96 tests green, ruff clean**.

This document maps every bullet in `SECURITY.md` to a concrete code location
and/or passing test.

---

## §0 Spec-flagged risks

**Privacy leakage through over-parameterization**
- Every tool's `inputSchema` is field-specific. `propose_fields` lists exactly the 12
  proposable fields; `extract_doc` takes only `document_type`. No tool schema accepts
  SSNs, full bank details, or fields beyond its stated purpose.
- Server-side allowlist in `form.py::PROPOSABLE_FIELDS` re-enforces this independently
  of the schema.
- Test: `test_security.py::test_propose_allowlist_blocks_arbitrary_fields`

**Tools as attack targets (no tool is the final commit path)**
- `POST /form/submit` is a standard HTML form POST, not a WebMCP tool, and requires a
  CSRF token. There is no `registerTool()` call that touches `Session.status`.
- Tests: `test_security.py::test_submit_requires_human_post_not_api`,
  `test_propose_cannot_set_session_status`, `test_save_progress_cannot_submit`

**`readOnlyHint` is a hint, not a boundary**
- Server-side hooks (`hooks.py::pre_execute_hook`) enforce rate limiting and audit
  logging regardless of hint value. `readOnlyHint` is correctly set per architecture
  table (3 true, 3 false) and verified by automated test.
- Test: `test_security.py::test_readOnlyHint_values_in_js`

**Same-origin boundary risk in multi-origin browsing**
- No `exposedTo` is set on any tool. All tools are same-origin only by default.
  Sensitive data (session ID, field values) is server-side only; tool responses contain
  only structured `{field_name: value}` pairs, never full session context.
- Test: `test_security.py::test_no_exposedTo_in_js`

**BFCache / document lifecycle**
- Declarative forms use `SubmitEvent#respondWith()` to avoid full-page navigation, which
  sidesteps BFCache abandonment for in-flight tool calls. No tool flow assumes a call
  survives a navigation.

---

## §1 The agent is not the user

**Never let a tool call be the final irreversible action**
- The `POST /form/submit` endpoint requires `session.status != "submitted"`, a valid
  CSRF token, and a human-initiated form POST. No WebMCP tool can call it.
- Tests: `test_submit_requires_human_post_not_api`, `test_submit_csrf_required`

**Re-validate every input server-side**
- `api_propose` validates each field name against `PROPOSABLE_FIELDS` and each value
  through `_validate_proposed_field()` — same rules as human input, independent of
  `inputSchema`.
- `extract_doc` endpoint validates `document_type` explicitly.
- Tests: `test_propose_invalid_value_skipped`, `test_propose_unknown_field_skipped`

**Uncommitted/proposal pattern**
- Every agent-written `FieldValue` has `committed=False`. Commit requires a human POST
  to `/form/commit/{field}` or `/form/commit_all` with a valid CSRF token.
- Tests: `test_propose_always_uncommitted`, `test_propose_never_writes_committed_true`,
  `test_extract_endpoint_creates_uncommitted_rows`

---

## §2 Prompt injection via document content

**Document text treated as adversarial**
- `services/extraction.py` applies `_is_injection()` to every extracted candidate before
  it's returned. Known injection phrases cause the entire candidate to be silently
  dropped, not logged or echoed.
- Extracted values must pass `_validate_candidate()` (same validators as human input)
  before leaving the module. Raw OCR text never reaches `documents.py` or `form.py`.
- Tests: `test_injection_in_document_is_blocked`, `test_injection_guard_blocks_known_phrases`

**Free-text field sanitization**
- All text rendered in `review.html` goes through Jinja2's autoescaping. No raw string
  concatenation builds HTML from tool output. Proposed and extracted values are plain
  strings stored in SQLite and rendered via `{{ value }}` (escaped by default).
- `hooks.py::sanitize_output()` coerces all tool result values to strings, removing
  any structured data that could be interpreted as instructions.

---

## §3 Tool design hygiene

**No god tools**
- Each tool operates on a specific, bounded scope. `propose_fields` has a 12-field
  allowlist enforced server-side. There is no `update_anything(field, value)` tool.
- Test: `test_propose_allowlist_blocks_arbitrary_fields`

**Honest descriptions**
- `propose_fields` description: "NOT committed until human clicks Accept" — explicitly
  signals it does not submit.
- `extract_doc` description: "Values are NOT committed — human reviews first."
- `save_progress` description: "Does not submit the application."
- `check_eligibility` / `flag_issues` / `explain_field` are `readOnlyHint: true` and
  their descriptions say nothing about writing.

**Idempotency**
- `_upsert_field()` uses `(session_id, field_name, committed)` as an upsert key, not
  insert-only. Repeated proposals for the same field update in place.
- Test: `test_propose_is_idempotent`

---

## §4 Standard web security

**CSRF on every mutating endpoint**
- HTML form endpoints (`/form/step/{n}`, `/form/submit`, `/form/commit/{field}`,
  `/form/reject/{field}`, `/form/commit_all`, `/form/reject_all`) all verify a
  `csrf_token` form field via `itsdangerous.URLSafeSerializer`. Invalid tokens → 403.
- JSON API endpoints (`/api/form/propose`, `/api/form/save`, `/api/documents/extract`)
  are additionally protected by `assert_same_origin()` — cross-origin requests with
  an `Origin` header not matching `Host` are rejected with 403.
- `SameSite=Lax` cookie flag prevents cross-site cookie attachment on cross-origin
  fetch POSTs, providing defence-in-depth at the browser level.
- Tests: `test_commit_csrf_required`, `test_submit_csrf_required`,
  `test_cross_origin_propose_rejected`, `test_same_origin_propose_allowed`

**Session cookies: HttpOnly, SameSite=Lax, Secure (prod)**
- `form.py::_set_session_cookie()` sets `httponly=True`, `samesite="lax"`,
  `secure=COOKIE_SECURE` (env-configurable, defaults `False` in dev, set `True` in prod).
- Tests: `test_session_cookie_is_httponly`, `test_session_cookie_is_samesite_lax`

**File upload validation**
- `ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}` checked
  against `upload.content_type` before saving. Files exceeding 10 MB are rejected.
- Files stored in `./uploads/` (outside `app/static/`). Never executed or directly served.
- `extraction.py` is the only code path that reads uploaded files.

**Output encoding**
- All template output uses Jinja2 autoescaping. No `{{ value | safe }}` is used for
  agent-proposed or extracted content.

**Rate limiting**
- 20 calls/60 s/session/tool enforced by in-memory sliding window in `hooks.py`.
  Call 21 returns `429 Too Many Requests`.
- Tests: `test_rate_limit_hammer_propose`, `test_rate_limit_per_tool_isolation`,
  `test_rate_limit_window_slides`

**No secrets in JS**
- `webmcp-tools.js` contains only fetch() calls to relative URL paths. No API keys,
  DB credentials, or session secrets appear in any static file.
- Test: `test_no_secrets_in_js`

---

## §5 Origin and exposure scope

**No `exposedTo` on any tool**
- `webmcp-tools.js` does not set `exposedTo` in any `registerTool()` call. All 8 tools
  are same-origin only. The file contains one `console.error` guard that references the
  string "exposedTo" in an error message context only — no tool registration uses it.
- Test: `test_no_exposedTo_in_js`

**No `allow="tools"` iframes**
- No templates embed iframes. No `allow="tools"` appears anywhere in the codebase.

---

## §6 Auditability

**Every tool call logged**
- `hooks.py::pre_execute_hook()` creates a `ToolCallLog` row with `outcome="pending"`
  before execution. `post_execute_hook()` closes it with the final outcome and redacted
  output.
- Tests: `test_propose_creates_audit_log_row`, `test_save_progress_creates_audit_log_row`

**Logs never store raw doc bytes**
- `ToolCallLog.input_json` for `extract_doc` stores `{"document_type": "..."}` only —
  the file path and OCR text never reach the log.
- `redact_pii_for_log()` in `hooks.py` additionally strips email addresses from log
  payloads before storage.

---

## §7 Anti-patterns

**No "confirm" as another tool**
- The accept/reject flow is a standard HTML form POST to `/form/commit/{field}` and
  `/form/reject/{field}`. These endpoints are not registered as WebMCP tools and cannot
  be called via `document.modelContext`.

**No blind `exposedTo` defaults**
- `webmcp-tools.js` uses `document.modelContext.registerTool()` with no `exposedTo`.
  The WHATWG draft default (same-origin only) is the intended behavior.

**No raw extracted text in UI or logs**
- `extraction.py` never returns raw OCR text. `review.html` renders only
  `{{ proposed }}` values that have passed field-level validation. No debug panel
  displays document bytes.

---

## Automated evidence summary

| Check | Test | Result |
|---|---|---|
| Rate limit (20/min) | `test_rate_limit_hammer_propose` | PASS |
| Rate limit per-tool isolation | `test_rate_limit_per_tool_isolation` | PASS |
| Rate limit window slides | `test_rate_limit_window_slides` | PASS |
| CSRF on commit | `test_commit_csrf_required` | PASS |
| CSRF on reject | `test_reject_csrf_required` | PASS |
| CSRF on commit_all | `test_commit_all_csrf_required` | PASS |
| CSRF on submit | `test_submit_csrf_required` | PASS |
| Submit gate (propose can't submit) | `test_propose_cannot_set_session_status` | PASS |
| Submit gate (save can't submit) | `test_save_progress_cannot_submit` | PASS |
| Submit requires human POST | `test_submit_requires_human_post_not_api` | PASS |
| Proposals always uncommitted | `test_propose_always_uncommitted` | PASS |
| Field allowlist (no god tool) | `test_propose_allowlist_blocks_arbitrary_fields` | PASS |
| Idempotency (upsert, not insert) | `test_propose_is_idempotent` | PASS |
| Cross-origin rejection | `test_cross_origin_propose_rejected` | PASS |
| Same-origin allowed | `test_same_origin_propose_allowed` | PASS |
| Cookie HttpOnly | `test_session_cookie_is_httponly` | PASS |
| Cookie SameSite=Lax | `test_session_cookie_is_samesite_lax` | PASS |
| No exposedTo in JS | `test_no_exposedTo_in_js` | PASS |
| No secrets in JS | `test_no_secrets_in_js` | PASS |
| No toolautosubmit in templates | `test_no_toolautosubmit_in_templates` | PASS |
| readOnlyHint correctness | `test_readOnlyHint_values_in_js` | PASS |
| untrustedContentHint on extract_doc | `test_extract_doc_has_untrustedContentHint` | PASS |
| Audit log created (propose) | `test_propose_creates_audit_log_row` | PASS |
| Audit log created (save) | `test_save_progress_creates_audit_log_row` | PASS |
| Single mutation path | `test_extract_and_propose_share_mutation_path` | PASS |
