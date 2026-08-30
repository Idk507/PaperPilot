# PHASES.md — Build Plan (Revised)

Work phases in order. Do not start a phase until the previous one's exit criteria are all
checked. Each phase ends in a **working, demoable state** — treat every phase boundary as
if you might have to submit right then.

**Deadline:** Sep 3, 2026 at 1:00 PM PDT.
**Today:** Aug 30, 2026. Effective time budget ≈ 4 days — schedule is tight, phases are
ordered by demo-day criticality, not alphabetically.

**Before writing any code:** re-read `INSTRUCTIONS.md` top to bottom. Then re-read
`ARCHITECTURE.md`, `SECURITY.md`, `HOOKS.md`, and `SKILLS.md`. They are load-bearing
documents, not reference material.

---

## Phase 0 — Scaffold (Day 1, ~2 hours)

**Goal:** empty but running FastAPI app with the exact folder layout from `ARCHITECTURE.md`.
Every subsequent phase drops code into a pre-existing, known-good structure.

### Tasks

- [ ] `git init` (already done if repo exists), add `LICENSE` (MIT) at repo root — required
      for the Devpost "About" section
- [ ] Create the full folder tree from `ARCHITECTURE.md` (even empty files/dirs):
  ```
  app/
    main.py
    db.py
    models.py
    routers/
      __init__.py
      form.py
      eligibility.py
      documents.py
      explain.py
      audit.py
    services/
      __init__.py
      rules_engine.py
      extraction.py
      hooks.py
    templates/
      base.html
      form_step_1.html
      form_step_2.html
      form_step_3.html
      review.html
    static/
      webmcp-tools.js
      style.css
  tests/
    __init__.py
    test_smoke.py
  requirements.txt
  render.yaml
  .pre-commit-config.yaml
  ```
- [ ] `requirements.txt` — pin these exact packages (add version numbers via pip):
  `fastapi`, `uvicorn[standard]`, `sqlmodel`, `pydantic`, `jinja2`, `python-multipart`,
  `pdfplumber`, `pytesseract`, `Pillow`, `ruff`, `pytest`, `httpx`, `pre-commit`,
  `slowapi` (for rate limiting)
- [ ] `app/main.py`: FastAPI app that mounts routers + static files, serves a placeholder
  `/` route that renders `base.html`
- [ ] `app/db.py`: SQLModel engine setup, `create_db_and_tables()` call on startup,
  defines the three tables: `Session`, `FieldValue`, `ToolCallLog` — copy exact schema
  from `ARCHITECTURE.md`'s "Data model" section
- [ ] `app/models.py`: Pydantic request/response schemas (empty stubs are fine now, to be
  filled in Phase 1)
- [ ] `render.yaml`: single Python web service, `startCommand: uvicorn app.main:app
  --host 0.0.0.0 --port $PORT`
- [ ] `.pre-commit-config.yaml` wiring `ruff check app/` and `pytest tests/ -q`; run
  `pre-commit install`
- [ ] `tests/test_smoke.py`: single test — `GET /` returns 200

### What the WebMCP pieces look like at end of Phase 0

`static/webmcp-tools.js` is a **stub** with just a feature-detection guard and AbortController
scaffolding wired up:
```js
// Feature-detect using document.modelContext (navigator.modelContext deprecated Chrome 150+)
const mc = document.modelContext;
if (!mc) {
  console.warn("PaperPilot: WebMCP not available in this browser. Agent features disabled.");
}

// Each tool registration gets its own AbortController so it can be torn down independently.
// Store controllers here so cleanup is always possible even if registration is async.
const _toolControllers = {};
```
No tools are registered yet — controllers and registrations come in Phase 3.

### Exit criteria

- [ ] `uvicorn app.main:app --reload` boots clean from a fresh clone (no import errors)
- [ ] `GET /` returns 200
- [ ] `pytest tests/ -q` passes
- [ ] `ruff check app/` passes (zero warnings)
- [ ] `pre-commit install` is done; `git commit` triggers lint + tests

---

## Phase 1 — Human-only form flow (Day 1–2, ~5 hours)

**Goal:** A complete, multi-step application form that works with zero AI involvement.
This is your fallback demo if WebMCP has issues on demo day — it must be rock-solid.

### The mock grant: "Small Business Recovery Grant"

Three steps, each a separate HTML section (not a separate page navigation — use a
single-page JS step controller so tools don't need re-registration on each step):

**Step 1 — Business Info**
| Field | `name` attr | Type | Validation |
|---|---|---|---|
| Business legal name | `business_name` | text | required, 2–200 chars |
| Business type | `business_type` | select: `sole_proprietor`, `llc`, `corporation`, `nonprofit` | required |
| Year founded | `year_founded` | number | required, 1800–current year |
| State of registration | `state` | select: all 50 US states | required |
| EIN (Employer ID) | `ein` | text | pattern `\d{2}-\d{7}` or empty (sole proprietors) |

**Step 2 — Financial Info**
| Field | `name` attr | Type | Validation |
|---|---|---|---|
| Annual gross revenue | `annual_revenue` | number | required, ≥ 0 |
| Full-time employee count | `employee_count` | number | required, ≥ 0 |
| Revenue drop % (last year) | `revenue_drop_pct` | number | required, 0–100 |
| Primary use of funds | `use_of_funds` | select: `payroll`, `rent_utilities`, `equipment`, `inventory`, `other` | required |
| Describe use of funds | `use_of_funds_detail` | textarea | required if `use_of_funds=other`, max 500 chars |

**Step 3 — Supporting Documents + Review**
| Field | `name` attr | Type | Validation |
|---|---|---|---|
| Most recent tax return (PDF/image) | `tax_return_doc` | file | optional, MIME allowlist, ≤ 10 MB |
| Bank statement (PDF/image) | `bank_statement_doc` | file | optional, same constraints |
| Applicant full name | `applicant_name` | text | required |
| Applicant email | `applicant_email` | email | required |
| Certify truthfulness | `certify` | checkbox | must be checked |

### Tasks

- [ ] **`app/db.py`**: fully implement `Session`, `FieldValue`, `ToolCallLog` models
- [ ] **`app/models.py`**: Pydantic schemas for `FieldValueIn`, `FieldValueOut`,
  `SessionOut`, `FormStepSubmit` — typed, not `dict`
- [ ] **`routers/form.py`**:
  - `POST /form/start` → creates `Session`, sets `HttpOnly; Secure; SameSite=Lax` cookie
  - `GET /form/` → renders `form_step_1.html` (or resumes at current step from session)
  - `POST /form/step/{step_num}` → validates step fields via Pydantic, upserts `FieldValue`
    rows with `source="human"`, `committed=True`, redirects to next step
  - `GET /form/review` → renders `review.html` showing all committed field values
  - `POST /form/submit` → validates `Session.status` is not already `submitted`, flips
    status, renders `thank_you.html`
- [ ] **`services/rules_engine.py`**: placeholder eligibility function `check_eligibility(session_id) -> dict`
  returning `{"eligible": None, "reasons": []}` — Phase 3 fills in real logic
- [ ] **Templates**: `base.html` with nav, `form_step_1.html`, `form_step_2.html`,
  `form_step_3.html`, `review.html` — clean, readable HTML, proper `<label for>` on every
  field, Jinja2 autoescaping on all rendered values (never bypass with `| safe`)
- [ ] **`style.css`**: minimal but respectable; include stub rules for
  `:tool-form-active` and `:tool-submit-active` CSS pseudo-classes (used in Phase 2)
- [ ] **Session cookie**: set on `POST /form/start`, read on every subsequent request via
  a FastAPI dependency `get_current_session()`; return 400 if cookie missing on
  session-required routes
- [ ] **Save/resume**: `GET /form/` checks the session cookie; if a session exists and
  has field values, it pre-fills the form and jumps to the correct step
- [ ] **`tests/`**: add `test_form_flow.py` covering the full human path end-to-end using
  `httpx.AsyncClient`

### Security items to check before moving on

Re-run the `SKILLS.md` Security Review skill:
- [ ] Every mutating endpoint (`POST /form/step/*`, `POST /form/submit`) re-validates
  all fields server-side with Pydantic, independent of the HTML form
- [ ] Jinja2 autoescaping is on for all templates (default in Jinja2, verify it's not
  disabled anywhere)
- [ ] Session cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax`
- [ ] `POST /form/submit` cannot be called twice on the same session

### Exit criteria

- [ ] A human with zero AI agent can complete, save, resume, and submit the form through
  the plain browser UI
- [ ] `pytest tests/ -q` passes including `test_form_flow.py`
- [ ] `ruff check app/` passes

---

## Phase 2 — Declarative WebMCP tools (Day 2, ~2 hours)

**Goal:** let the browser auto-expose the `<form>` elements on Steps 1 and 2 as tools,
with no custom JS yet. This gives the agent the ability to fill visible form fields for
free, using only HTML attribute annotations.

### How declarative tools work (Chrome Declarative API, confirmed from live docs)

Add these attributes to each `<form>` on the step pages:
- `toolname` → stable machine identifier, **max 30 characters**, snake_case
- `tooldescription` → plain-language description, **max 500 characters**
- No `toolautosubmit` — deliberately omitted so the agent fills fields but the human
  must click Submit (this is our human-approval gate, built in by the spec for free)

Add `toolparamdescription` on each `<input>` / `<select>` / `<textarea>` — feeds that
field's description in the auto-synthesized `inputSchema`. **Max 150 characters each.**
The `name` attribute on each input maps to the schema property key — already needed for
normal form handling, so this is nearly free.

**CSS pseudo-classes (confirmed in Chrome docs):**
- `:tool-form-active` → applied to the `<form>` element when agent is filling it
- `:tool-submit-active` → applied to the form's `<button type="submit">` or
  `<input type="submit">` element (not the form itself)
- Both deactivate on submit, agent cancel, or user reset

**`toolactivated` / `toolcancel` events fire on `window`** (not on the form):
```js
window.addEventListener("toolactivated", ({ toolName }) => { /* agent filled form */ });
window.addEventListener("toolcancel",    ({ toolName }) => { /* agent/user cancelled */ });
```

**`SubmitEvent.respondWith()`** — call `event.preventDefault()` first, then resolve a
promise with the JSON result for the agent. This avoids full-page navigation entirely
(critical — the navigation-response mechanism is still unresolved per spec open issues).

### Tasks

- [ ] **Re-read** the Chrome Declarative API page before making any changes:
  https://developer.chrome.com/docs/ai/webmcp/declarative-api
- [ ] **`form_step_1.html`**: add `toolname="submit_biz_details"` (≤30 chars),
  `tooldescription="Submit Step 1 business info for the grant application. Fills business name, type, founding year, state, and EIN."` (≤500 chars) to the `<form>`;
  add `toolparamdescription` (≤150 chars each) to every input/select
- [ ] **`form_step_2.html`**: same treatment, `toolname="submit_fin_details"`,
  `tooldescription="Submit Step 2 financial info for the grant: annual revenue, employee count, revenue drop %, and use of funds."`
- [ ] **`style.css`**: add rules:
  ```css
  form:tool-form-active {
    outline: 2px dashed #3b82f6;
    outline-offset: 4px;
    background: #eff6ff;
  }
  button:tool-submit-active,
  input[type="submit"]:tool-submit-active {
    outline: 2px dashed #f59e0b;
    outline-offset: 2px;
  }
  ```
- [ ] **`webmcp-tools.js`**: add `submit` listener on both forms that calls
  `event.preventDefault()` then `event.respondWith(fetch(action, {method:"POST", body: new FormData(form)}).then(r => r.json()))` 
  — but only when `event.agentInvoked` is true; otherwise let the normal submission proceed
- [ ] **`SubmitEvent.agentInvoked`**: when `true`, also fire `POST /api/audit/log` so
  agent-driven declarative form submissions appear in `ToolCallLog`
- [ ] **`window` event listeners for `toolactivated` / `toolcancel`**: log to console and
  optionally update audit log with `toolName`
- [ ] **Update `ARCHITECTURE.md` tool table** with the two declarative tools
- [ ] **Manual test in Chrome**: enable `chrome://flags/#enable-webmcp-testing` OR join
  the origin trial (Chrome 149–156). Install the **Model Context Tool Inspector** extension
  (`chromewebstore.google.com/detail/model-context-tool-inspec/gbpdfapgefenggkahomfgkhfehlcenpd`)
  — it lets you see registered tools, fill parameters, and execute them in DevTools

### Exit criteria

- [ ] Human-only path still works with zero regressions
- [ ] An agent in a WebMCP-enabled browser can fill visible form fields on Steps 1 and 2
  without any custom JS tool code (just HTML attributes)
- [ ] Neither form has `toolautosubmit`; the spec requires human to click Submit
- [ ] `SECURITY.md` checklist re-run for anything touched in this phase

---

## Phase 3 — First imperative tools: read-only (Day 2–3, ~3 hours)

**Goal:** `explain_field` and `check_eligibility` — no state mutation, lowest-risk tools
first. These are the tools most likely to wow a judge ("the agent can explain what a
confusing field means") with the least architectural risk.

### Tool specifications (character-budget compliant, confirmed against Chrome docs)

**Character budgets from Chrome's own security guidance:**
- Tool name: ≤ 30 characters
- Tool description: ≤ 500 characters
- Parameter description: ≤ 150 characters per field
- Tool output: ≤ 1,500 characters per response

**`explain_field`**
- Kind: Imperative, `readOnlyHint: true`, `untrustedContentHint: false`
- Name: `explain_field` (13 chars ✓)
- Description (≤500 chars): `"Returns a plain-language explanation of a grant form field — what it means, why it's asked, and what a correct answer looks like. Use when the applicant is confused about a field name or requirement."`
- `inputSchema`:
  ```json
  {
    "type": "object",
    "properties": {
      "field_name": {
        "type": "string",
        "enum": ["business_name","business_type","year_founded","state","ein",
                 "annual_revenue","employee_count","revenue_drop_pct",
                 "use_of_funds","use_of_funds_detail","tax_return_doc",
                 "bank_statement_doc","applicant_name","applicant_email","certify"],
        "description": "The form field name to explain. Must be one of the 15 grant application fields."
      }
    },
    "required": ["field_name"]
  }
  ```
- Backing endpoint: `GET /api/explain/{field_name}`
- Execute return: plain string ≤1.5K chars (JSON.stringify the explanation dict)
- Justification comment: `// Replaces Googling "what is EIN" mid-form. Declarative <form> tool cannot return contextual explanations.`

**`check_eligibility`**
- Kind: Imperative, `readOnlyHint: true`, `untrustedContentHint: false`
- Name: `check_eligibility` (17 chars ✓)
- Description: `"Runs the eligibility rules against the current session's saved form data. Returns pass/fail and the specific disqualifying reasons. Use before submit to surface issues early."`
- `inputSchema`: `{ "type": "object", "properties": {}, "required": [] }` — reads server-side session, no args
- Backing endpoint: `POST /api/eligibility/check`
- Execute return: JSON string `{"eligible": bool, "reasons": [...]}` ≤1.5K chars
- Justification comment: `// Multi-condition rules require all saved field values from session. Cannot be expressed as a <form> tool.`

**`flag_missing_or_risky`** (bonus read-only)
- Kind: Imperative, `readOnlyHint: true`, `untrustedContentHint: false`
- Name: `flag_issues` (11 chars ✓ — shortened to fit budget)
- Description: `"Scans the current session for empty fields, inconsistencies (e.g. 0 employees but payroll as use of funds), and common rejection triggers. Returns a list of field names with a short reason each."`
- `inputSchema`: `{ "type": "object", "properties": {}, "required": [] }`
- Backing endpoint: `GET /api/eligibility/flags`

### Tasks

- [ ] **`routers/eligibility.py`**:
  - `POST /api/eligibility/check` → calls `services/rules_engine.py::check_eligibility()`
  - `GET /api/eligibility/flags` → calls `services/rules_engine.py::flag_missing_or_risky()`
  - Both endpoints: session validation, then pre/post hook pipeline from `hooks.py`
- [ ] **`services/rules_engine.py`**: implement real eligibility rules:
  - `annual_revenue` ≤ $5M (disqualifying if > $5M)
  - `employee_count` ≤ 500
  - `revenue_drop_pct` ≥ 15% (required to qualify)
  - `year_founded` ≤ current year - 1 (business must be ≥ 1 year old)
  - Returns `{"eligible": bool, "reasons": [{"field": str, "reason": str}]}`
- [ ] **`routers/explain.py`**: `GET /api/explain/{field_name}` — looks up from a static
  dict of field explanations (hardcoded plain-language strings — no LLM needed, more
  reliable for demo); validates `field_name` against enum server-side before lookup
- [ ] **`routers/audit.py`**: `POST /api/audit/log` endpoint used by the `SubmitEvent`
  handler from Phase 2; writes to `ToolCallLog` with `source="declarative_form"`
- [ ] **`services/hooks.py`**: implement the full pre/post hook pipeline from `HOOKS.md`:
  ```python
  async def pre_execute_hook(session_id, tool_name, payload) -> str:  # returns log_id
  async def post_execute_hook(log_id, result, outcome) -> dict
  ```
  Rate limit: 20 calls/min/session. Use `slowapi` for the rate-limiting decorator.
- [ ] **`webmcp-tools.js`**: register all three tools using the **exact** pattern:
  ```js
  // One controller per tool so each can be torn down independently (Chrome 150+).
  // On Chrome 153+ aborting a controller no longer cancels in-flight executions.
  const mc = document.modelContext;
  if (!mc) return;

  const explainController = new AbortController();
  try {
    await mc.registerTool({
      name: "explain_field",            // ≤30 chars
      description: "...",               // ≤500 chars
      inputSchema: { ... },
      annotations: { readOnlyHint: true, untrustedContentHint: false },
      execute: async ({ field_name }, { signal }) => {
        const res = await fetch(`/api/explain/${encodeURIComponent(field_name)}`, { signal });
        if (!res.ok) throw new Error(`explain_field: HTTP ${res.status}`);
        const data = await res.json();
        return JSON.stringify(data);    // plain string, ≤1.5K chars
      }
    }, { signal: explainController.signal });
  } catch (e) {
    // Surface every error type explicitly (INSTRUCTIONS.md rule #9)
    if (e.name === "InvalidStateError") console.error("WebMCP: InvalidStateError registering explain_field:", e.message);
    else if (e.name === "NotAllowedError") console.error("WebMCP: tools Permissions Policy disabled");
    else if (e.name === "SecurityError")   console.error("WebMCP: SecurityError on exposedTo origin");
    else if (e.name === "TypeError")       console.error("WebMCP: TypeError — invalid inputSchema");
    else throw e;
  }
  _toolControllers.explain_field = explainController;
  ```
  Repeat the same pattern for `check_eligibility` and `flag_issues`.
- [ ] **Update `ARCHITECTURE.md` tool table** with all three tools and their `readOnlyHint` values
- [ ] **`tests/`**: `test_eligibility.py` — ≥5 test cases covering each disqualifier and the happy path

### Security items before moving on

- [ ] `explain_field` endpoint rejects any `field_name` not in the explicit enum —
  even if the `inputSchema` already lists it; server-side re-check is mandatory
- [ ] `check_eligibility` and `flag_missing_or_risky` are truly read-only: verify they
  write zero `FieldValue` rows
- [ ] All three tools correctly set `readOnlyHint: true` — no exceptions

### Exit criteria

- [ ] Both tools callable end-to-end (Chrome, WebMCP flag on)
- [ ] All calls logged in `ToolCallLog`
- [ ] `SECURITY.md` checklist re-run
- [ ] `pytest tests/ -q` passes

---

## Phase 4 — State-mutating tools + review/commit UI (Day 3, ~5 hours)

**Goal:** `propose_field_values`, the uncommitted-diff UI, and the human-approval flow.
This is the **architectural core** of the project — take the extra time here. This phase
is what makes PaperPilot a real demo, not a toy.

### How the uncommitted pattern works

1. Agent calls `propose_field_values` with a dict of `{field_name: value}` pairs
2. FastAPI writes `FieldValue` rows with `committed=False`, `source="agent_proposed"`
3. `review.html` renders proposed-vs-current as a visible diff: highlight color, badge
4. Accept / Reject buttons hit `/api/form/commit/{field_name}` and
   `/api/form/reject/{field_name}` — **normal, non-WebMCP, authenticated endpoints**
   (never WebMCP tools — see `ARCHITECTURE.md` step 7-8 and `SECURITY.md` section 7)
5. Accept flips `committed=True`; Reject deletes the uncommitted row
6. The `hooks.py` post-execute hook enforces: no tool call can ever return a
   `committed=True` row — this is checked in `hooks.py`, not just convention

### Tool specifications (character-budget compliant)

**`propose_field_values`**
- Kind: Imperative, `readOnlyHint: false` (explicitly set), `untrustedContentHint: false`
- Name: `propose_fields` (14 chars ✓ — shortened from `propose_field_values`)
- Description (≤500 chars): `"Proposes a set of field values for the human to review. Values are NOT committed until the human clicks Accept. Call after gathering info from conversation or documents to suggest pre-fills."`
- `inputSchema`: object with the 15 field names as optional properties (explicit allowlist,
  no `additionalProperties: true`)
- Backing endpoint: `POST /api/form/propose`
- Execute return: `JSON.stringify({ proposed: [...field names], message: "N fields proposed for review." })` ≤1.5K chars
- Justification comment: `// Batch-proposes values without committing. Declarative <form> tool submits directly and cannot hold uncommitted state.`

**`save_progress`**
- Kind: Imperative, `readOnlyHint: false`, `untrustedContentHint: false`
- Name: `save_progress` (13 chars ✓)
- Description: `"Saves the current form session so the applicant can resume later. Does not submit the application. Safe to call at any point during form completion."`
- `inputSchema`: `{ "type": "object", "properties": {}, "required": [] }`
- Backing endpoint: `POST /api/form/save`
- Execute return: plain string `"Progress saved."` ≤1.5K chars ✓

### Tasks

- [ ] **`routers/form.py`**: add:
  - `POST /api/form/propose` → pre-execute hook, validate each field name against allowlist,
    upsert `FieldValue(committed=False, source="agent_proposed")` for each, post-execute hook
  - `POST /api/form/save` → updates `Session.updated_at`, returns success JSON
  - `POST /api/form/commit/{field_name}` → **non-WebMCP endpoint**, flips `committed=True`
    for one field, requires valid session cookie + CSRF token
  - `POST /api/form/reject/{field_name}` → **non-WebMCP endpoint**, deletes the
    uncommitted `FieldValue` row for that field
  - `POST /api/form/commit_all` → commits all uncommitted rows in one action
  - `POST /api/form/reject_all` → rejects all uncommitted rows
- [ ] **`hooks.py`**: add post-execute enforcement: scan the result dict for any
  `committed=True` fields; if found, log an error and remove them before returning.
  This is the hard enforcement boundary.
- [ ] **`review.html`**: redesign this template to show:
  - Current committed values (what the human typed) in normal style
  - Proposed uncommitted values from agent in a highlighted diff style
    (e.g. yellow background + "Agent suggested" badge)
  - Accept / Reject button per field (POST to the commit/reject endpoints above)
  - "Accept all" / "Reject all" bulk actions
  - Use `:tool-form-active` CSS class on sections the agent just populated
- [ ] **CSRF protection**: add a CSRF token to the commit/reject forms (FastAPI middleware
  or a simple double-submit cookie approach); the `POST /api/form/commit/*` endpoints must
  verify the token
- [ ] **`webmcp-tools.js`**: register `propose_field_values` and `save_progress` with
  full try/catch error handling on `registerTool()`. Wrap responses back to the agent
  as `{ content: [{ type: "text", text: JSON.stringify(result) }] }`
- [ ] **Update `ARCHITECTURE.md` tool table** with both new tools
- [ ] **`tests/`**: `test_propose.py` — test that `POST /api/form/propose` creates
  uncommitted rows, that `POST /api/form/commit/{field}` commits them, that a tool call
  can never produce `committed=True` rows directly

### Security items before moving on

- [ ] `POST /api/form/commit/*` and `POST /api/form/reject/*` are **never** called from
  `webmcp-tools.js` — they are human-only UI actions
- [ ] `propose_field_values` input validated server-side: each field name in explicit
  allowlist, each value run through the same Pydantic validators as human-typed input
- [ ] Idempotency: `propose_field_values` upserts (session + field_name key), not inserts —
  agent retries don't double-write
- [ ] Rate limit on `POST /api/form/propose` (same 20 calls/min/session as other tools)
- [ ] CSRF token verified on all commit/reject endpoints

### Exit criteria

- [ ] Agent can propose a batch of field values
- [ ] Human sees exactly what changed before anything commits (visible diff in `review.html`)
- [ ] Human can accept or reject per field, or bulk accept/reject
- [ ] No tool call path can directly commit a field value — verified by `test_propose.py`
- [ ] `SECURITY.md` checklist re-run

---

## Phase 5 — Document extraction tool (Day 3–4, ~4 hours)

**Goal:** `extract_from_document` — the most impressive, most differentiating tool. An
agent can say "I see you uploaded your tax return — let me pre-fill the income fields."

**`extract_from_document`**
- Kind: Imperative, `readOnlyHint: false`, `untrustedContentHint: true`
  (⚠️ this is the one tool that returns user-generated/external content downstream —
  set `untrustedContentHint: true` so browser-integrated agents apply spotlighting)
- Name: `extract_doc` (11 chars ✓ — shortened)
- Description (≤500 chars): `"Reads an already-uploaded document (tax return or bank statement from Step 3) and extracts field values to propose as pre-fills. Extracted values are NOT committed — the human reviews them first. Use after the applicant uploads a document."`
- `inputSchema`:
  ```json
  {
    "type": "object",
    "properties": {
      "document_type": {
        "type": "string",
        "enum": ["tax_return", "bank_statement"],
        "description": "Which uploaded document to extract from. Must be uploaded first on Step 3."
      }
    },
    "required": ["document_type"]
  }
  ```
- Backing endpoint: `POST /api/documents/extract`
- Execute return: `JSON.stringify({ proposed: [...], skipped: [...], message: "..." })` ≤1.5K chars
  — **never** raw OCR text
- Justification comment: `// Requires reading a server-side binary file and running OCR. Cannot be a declarative <form> tool.`

### Tasks

- [ ] **Upload endpoint** (already partially wired in Phase 1 for Step 3):
  `POST /api/documents/upload` — enforce:
  - MIME type allowlist: `application/pdf`, `image/png`, `image/jpeg`, `image/tiff`
  - Max size: 10 MB
  - Store file outside any publicly served static path (e.g. `./uploads/` dir, not
    `app/static/`)
  - Return a `doc_id` (UUID), store path in the session's metadata (a new `Document`
    model or a metadata column on `Session`)
  - Never execute or directly serve uploaded files
- [ ] **`services/extraction.py`**:
  - Primary: `pdfplumber` for PDFs — extract text, parse for dollar amounts, EIN patterns,
    employee counts, business names using regex
  - Fallback: `pytesseract` for images — OCR the image then apply same regex parsing
  - Return `dict[str, str]` of `{field_name: extracted_value}` for fields recognized
  - **Sanitization (mandatory, `SECURITY.md` section 2):** strip all extracted text of
    anything resembling a prompt instruction before it ever reaches the tool response.
    Concretely: extracted values are run through the same Pydantic validators as
    human-typed input — if a value doesn't validate, it's dropped, never echoed back.
    Never put raw OCR text in a tool response or a tool description.
- [ ] **`routers/documents.py`**:
  - `POST /api/documents/extract` → pre-execute hook, calls `extraction.py`, sanitizes
    output, routes extracted fields into the same `propose_field_values` path
    (calls `routers/form.py::propose_fields()` internally — **one mutation path, not two**)
  - Returns `{ proposed: {field_name: value}, skipped: [fields where extraction failed] }`
- [ ] **`hooks.py`**: add `redact_pii_for_log()` — the `ToolCallLog` entry for
  `extract_from_document` must never store raw extracted text, only the structured
  `{field_name: value}` dict
- [ ] **UI**: add a "Extract from document" button to `review.html` (visible after a
  document is uploaded) that calls the `extract_from_document` tool or, for the human-only
  path, a regular form POST to `POST /api/documents/extract` (same endpoint, no JS required)
- [ ] **`tests/`**: `test_extraction.py` with sample PDF/image fixtures (synthetic,
  no real PII) confirming extraction + sanitization
- [ ] **Update `ARCHITECTURE.md` tool table**

### Security items before moving on

- [ ] Uploaded files are never directly served from a public URL
- [ ] MIME type re-checked server-side (not just the Content-Type header — use
  `python-magic` or `pdfplumber`'s own parser to confirm file is actually a PDF)
- [ ] Raw extracted text never echoed to the agent in a tool response — only validated
  field values
- [ ] `extract_from_document` uses the same proposal pipeline as `propose_field_values`
  (no second mutation path)

### Exit criteria

- [ ] Uploading a sample pay stub image/PDF produces reviewable proposed field values
- [ ] Proposed values are never auto-committed
- [ ] `SECURITY.md` checklist re-run
- [ ] `pytest tests/ -q` passes

---

## Phase 6 — Security hardening pass (Day 4 morning, ~2 hours)

**Goal:** run the full `SECURITY.md` checklist top to bottom, not spot checks.
This is a gate phase — no new features, only fixes and proof.

### Tasks

- [ ] Print out `SECURITY.md` and check off every bullet point with a one-line note on
  how it's satisfied in the code:
  - Section 0: Spec-flagged risks (privacy leakage, tool misuse, hint vs. boundary,
    same-origin multi-origin risk, BFCache)
  - Section 1: Agent ≠ user (no final WebMCP action, server-side validation, uncommitted pattern)
  - Section 2: Prompt injection (document extraction sanitization, free-text field sanitization)
  - Section 3: Tool design hygiene (no god tools, honest descriptions, idempotency)
  - Section 4: Standard web security (CSRF, cookie flags, file upload, output encoding, rate limiting, no secrets in JS)
  - Section 5: Origin/exposure scope (`exposedTo` not set anywhere)
  - Section 6: Auditability (every tool call logged, logs don't store raw doc bytes)
  - Section 7: Anti-patterns (no "confirm" as another tool, no blind `exposedTo` defaults)
- [ ] **Rate limiting**: hammer `POST /api/form/propose` with 25 rapid calls, confirm 429
  kicks in at call 21
- [ ] **CSRF**: attempt to submit a commit endpoint without the CSRF token, confirm 403
- [ ] **Submit gate**: attempt to flip `Session.status = submitted` directly via any
  WebMCP tool call — confirm impossible
- [ ] **`readOnlyHint` audit**: grep for all `registerTool(` calls and verify each has
  the correct `readOnlyHint` value per the tool table
- [ ] **`toolautosubmit` audit**: grep for `toolautosubmit` in all templates — must
  return zero results
- [ ] **Secrets audit**: grep all `.js` files for any key patterns — must return zero

### Exit criteria

- [ ] `SECURITY.md` checklist fully checked off with evidence (notes in the file itself
  or a new `SECURITY_AUDIT.md`)
- [ ] No unresolved security items

---

## Phase 7 — Demo, docs, submission (Day 4, ~3 hours)

**Goal:** everything Devpost requires, polished and submitted before the deadline.

### Tasks

- [ ] **`README.md`**: finalize with:
  - One-paragraph "what is this" (pull from `README.md`'s existing intro)
  - Prerequisites: Python 3.11+, Chrome 149+ with WebMCP flag, Tesseract installed
  - Local run instructions (exact commands)
  - Live URL on Render
  - How to test with an agent (which browser flag, what to say to the agent)
- [ ] **License**: confirm `LICENSE` file is at repo root and visible in GitHub's About
  section
- [ ] **Deploy to Render**: push to GitHub, connect repo in Render dashboard, use
  `render.yaml`. Verify live URL works in Chrome (WebMCP flag on) and Chrome (flag off —
  human-only path must still work)
- [ ] **Demo video** (<3 minutes):
  Use `SKILLS.md`'s "Demo Storytelling" skill script:
  - 0:00–0:15 — the problem ("filling out grant paperwork is confusing and error-prone")
  - 0:15–0:30 — human-only path working (establish baseline)
  - 0:30–2:00 — agent collaboration: `explain_field` ("what is EIN?"), `check_eligibility`,
    upload a document, `extract_from_document`, proposed-values diff, human accepts/rejects
  - 2:00–2:45 — explicitly say what WebMCP made possible (browser context reuse,
    human-in-the-loop guarantee, no blind backend automation)
  - 2:45–3:00 — live URL + repo link
- [ ] **Devpost submission text**: pull directly from `ARCHITECTURE.md`'s tool table and
  the WebMCP fit rationale in `README.md`. Specifically answer:
  - Why WebMCP fits this problem (not just "it's cool" — cite the structural fit:
    browser session auth reuse, human-in-loop via spec behavior, not blind backend automation)
  - What's newly possible (agent can explain, check eligibility, extract from uploaded
    docs, propose pre-fills — all while the human watches the same UI)
  - How it was implemented (imperative + declarative APIs, both used, with specific tool
    names and endpoints)
- [ ] **Final Definition of Done pass** (from `INSTRUCTIONS.md`):
  - [ ] Human-only path works, zero regressions
  - [ ] Every tool has a passing manual test in Chrome
  - [ ] Every mutating tool has `readOnlyHint` correctly set
  - [ ] No `toolautosubmit` without documented reason
  - [ ] All `HOOKS.md` pre/post-execute checks wired
  - [ ] `SECURITY.md` checklist checked off
  - [ ] `README.md` Quickstart boots app from clean clone

### Exit criteria

- [ ] Submitted on Devpost before Sep 3, 2026 1:00 PM PDT
- [ ] Live Render URL verified working
- [ ] Demo video uploaded

---

## Quick reference — Tool registry (from `ARCHITECTURE.md`)

| Tool name | Phase | Kind | `readOnlyHint` | Mutates? | Human confirm? |
|---|---|---|---|---|---|
| `submit_biz_details` | 2 | Declarative `<form>` | n/a | yes (direct, human clicks Submit) | yes — built into declarative spec |
| `submit_fin_details` | 2 | Declarative `<form>` | n/a | yes (direct, human clicks Submit) | yes — built into declarative spec |
| `explain_field` | 3 | Imperative | `true` | no | no |
| `check_eligibility` | 3 | Imperative | `true` | no | no |
| `flag_issues` | 3 | Imperative | `true` | no | no |
| `propose_fields` | 4 | Imperative | `false` | yes (uncommitted only) | yes, to commit |
| `save_progress` | 4 | Imperative | `false` | yes (session only) | no |
| `extract_doc` | 5 | Imperative | `false` + `untrustedContentHint: true` | yes (uncommitted only) | yes, to commit |

**The commit action is never a WebMCP tool.** Accepting proposed values always goes through
a human-only, authenticated, CSRF-protected endpoint.

---

## Phase ordering rationale

1. **Phase 0** first because every other phase assumes the folder structure exists.
2. **Phase 1** next because the human-only path is the fallback demo — without it, a
   WebMCP failure on demo day means no demo.
3. **Phase 2** before imperative tools because it's free (HTML attributes only) and
   covers two of the three form steps with zero custom JS risk.
4. **Phase 3** before Phase 4 because read-only tools are lower risk and prove the
   `hooks.py` pipeline before we add writes.
5. **Phase 4** is the core architecture — the commit/uncommitted pattern, the diff UI,
   and the human-approval flow.
6. **Phase 5** last (before hardening) because document extraction is the most complex,
   has the most security surface, and can be cut from the demo if time runs out without
   breaking anything else.
7. **Phase 6** is a gate, not an afterthought — run it before Phase 7.
8. **Phase 7** is submission, not "extra polish time."
