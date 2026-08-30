# ARCHITECTURE.md — System Design

## Source of truth

This document is written against the actual WebMCP spec/explainer, not assumption. Primary
references (read these, don't take this file's word for it):

- Spec explainer (fork used for this project): **https://github.com/Idk507/webmcp**
  (forked from the canonical spec repo, `webmachinelearning/webmcp`)
- Declarative API explainer: `declarative-api-explainer.md` in that repo
- Security & privacy self-review: `security-privacy-questionnaire.md` in that repo
- Rendered spec: https://webmachinelearning.github.io/webmcp/
- Chrome implementation docs: https://developer.chrome.com/docs/ai/webmcp
- TypeScript types: `webmcp-types` on npm

Anything in this file that contradicts those sources is wrong — those sources win.

## High-level shape

```
Browser (human + agent)
  ├─ Jinja2-rendered HTML pages (the human-facing form)
  ├─ /static/webmcp-tools.js  (thin tool registration + fetch wrappers)
  └─ document.modelContext    (browser-native WebMCP surface — Window + same-origin iframes
                                 by default; cross-origin only via exposedTo)
         │
         │  fetch('/api/...')
         ▼
FastAPI backend (all real logic lives here)
  ├─ routers/form.py          — CRUD for form sessions & field values
  ├─ routers/eligibility.py   — rules engine
  ├─ routers/documents.py     — upload + extraction
  ├─ routers/explain.py       — plain-language field explanations
  ├─ routers/audit.py         — tool-call logging (see HOOKS.md)
  └─ db.py                    — SQLModel models, SQLite for hackathon
```

No separate frontend framework, no build step. This keeps the whole project inside your
Python comfort zone except for one small JS file.

## Folder layout

```
paperpilot/
├── app/
│   ├── main.py                 # FastAPI app, mounts routers + static
│   ├── db.py                   # SQLModel models + session
│   ├── models.py                # Pydantic schemas (request/response contracts)
│   ├── routers/
│   │   ├── form.py
│   │   ├── eligibility.py
│   │   ├── documents.py
│   │   ├── explain.py
│   │   └── audit.py
│   ├── services/
│   │   ├── rules_engine.py     # pure Python, no FastAPI imports — testable
│   │   ├── extraction.py       # pdfplumber/pytesseract wrapper
│   │   └── hooks.py            # pre/post tool-execution hooks, see HOOKS.md
│   ├── templates/
│   │   ├── base.html
│   │   ├── form_step_*.html    # declarative-tool forms live here
│   │   └── review.html
│   └── static/
│       ├── webmcp-tools.js     # the ONLY substantial JS file in the project
│       └── style.css
├── tests/
├── requirements.txt
└── render.yaml                  # Render deployment config
```

## Data model (SQLite via SQLModel)

```python
class Session(SQLModel, table=True):
    id: str  # uuid, stored in a cookie
    created_at: datetime
    status: Literal["in_progress", "review", "submitted"]

class FieldValue(SQLModel, table=True):
    session_id: str
    field_name: str
    value: str
    source: Literal["human", "agent_proposed", "agent_committed", "document_extracted"]
    committed: bool = False   # uncommitted = agent proposal, not yet human-approved

class ToolCallLog(SQLModel, table=True):
    session_id: str
    tool_name: str
    input_json: str
    output_json: str
    timestamp: datetime
    outcome: Literal["success", "rejected_by_hook", "error"]
```

`FieldValue.committed=False` rows implement the "uncommitted changes" batch-edit pattern
described in the spec's own graphic-design use case (Jen/flyer example): the agent proposes
a batch of field values, the UI renders them as a diff/highlight, and only a human action
flips `committed=True`.

## The two real WebMCP registration mechanisms

WebMCP has **two distinct APIs** and this project uses both. Get the mechanics right —
this was wrong in an earlier draft of this doc.

### 1. Imperative API — `document.modelContext.registerTool()`

The actual signature (per the spec):

```js
const controller = new AbortController();

await document.modelContext.registerTool({
  name: "check-eligibility",              // stable machine identifier
  title: "Check grant eligibility",        // optional, human-readable, shown in agent UI
  description: "Runs the eligibility rules engine against the current form state and " +
               "returns pass/fail plus the specific reasons.",
  inputSchema: {
    type: "object",
    properties: {},                       // this tool reads server-side session state,
    required: []                          // takes no direct arguments
  },
  annotations: {
    readOnlyHint: true                    // real spec field — signals this tool does not
                                           // mutate state, which can let an agent (or its
                                           // harness) skip a confirmation step for it
  },
  async execute(input, agent) {
    const res = await fetch('/api/eligibility/check', { method: 'POST' });
    const data = await res.json();
    return { content: [{ type: "text", text: JSON.stringify(data) }] };
  }
}, { signal: controller.signal });

// Unregister later (e.g. when a step of the form unmounts):
// controller.abort();
```

Key facts from the spec that change how we build this:
- `registerTool()` **throws real, typed errors**: `InvalidStateError` (inactive document,
  duplicate tool name, invalid name/description), `NotAllowedError` (the `"tools"`
  Permissions Policy is disabled), `SecurityError` (a non-trustworthy `exposedTo` origin),
  `TypeError` (schema fails to serialize). `webmcp-tools.js` must catch and surface these,
  not assume registration always succeeds.
- Tools are **tied to document lifetime** — no persistence across navigations. If our
  multi-step form ever does a full page navigation between steps (it shouldn't — see
  below), tools re-register per page.
- `document.modelContext` fires a `toolchange` event when tools are added/removed/updated —
  useful if we dynamically add tools per form step.
- `annotations.readOnlyHint` is real and matters for our tool table: **only** tools that
  truly never mutate state (`explain_field`, `check_eligibility`, `flag_missing_or_risky`)
  get `readOnlyHint: true`. Never set this on a tool that writes `FieldValue` rows, even
  uncommitted ones — see `SECURITY.md`.

### 2. Declarative API — `<form>` attributes

This is **not** "just add ARIA-ish labels," which an earlier draft of this doc incorrectly
implied. It's a specific attribute set that deterministically compiles a form to a WebMCP
tool:

```html
<form
  toolname="submit-business-details"
  tooldescription="Captures the applicant's business name, income, and employee count for the grant application."
  method="post" action="/form/step2">

  <input type="text" name="business_name"
         toolparamdescription="Legal registered name of the business" required>

  <input type="number" name="annual_income"
         toolparamdescription="Most recent annual gross income in USD" required>

  <button type="submit">Continue</button>
</form>
```

- `toolname` / `tooldescription` on `<form>` map directly to the imperative API's
  `name` / `description`.
- `toolparamdescription` on each input feeds that field's description in the
  auto-synthesized `inputSchema` (the `name` attribute supplies the schema property name —
  already something we need for normal form handling, so this is nearly free).
- `toolautosubmit` is a **boolean attribute we deliberately omit** on every form in this
  project. Per spec: without it, once an agent finishes filling the form, the browser
  focuses the submit button and the agent is expected to tell the human to review and
  submit manually. That manual-submit requirement is exactly our human-approval gate for
  free — we don't have to build it ourselves for declarative forms. Do not add
  `toolautosubmit` anywhere without a written reason in `SECURITY.md`.
- The `:tool-form-active` / `:tool-submit-active` CSS pseudo-classes let us visually
  highlight a form an agent just filled, waiting on the human — use this in `style.css`
  instead of building custom "agent is editing" UI state by hand.
- `SubmitEvent.agentInvoked` (a new boolean on the submit event) tells our own JS whether
  a given submission came from the agent or a human click — useful for `audit.py` logging
  without needing a separate signal.
- Getting the tool's response back to the agent without a full navigation uses
  `SubmitEvent#respondWith(promise)` — call `event.preventDefault()` first, then hand back
  a promise resolving to the JSON we want the agent to see. This is how our multi-step
  form avoids full page reloads while still working as a declarative tool.

## The WebMCP tool table

Keep this table current — it's also your submission's "how we implemented WebMCP" writeup.

**Character budgets (Chrome's own guidance):** tool name ≤30 chars, description ≤500 chars,
param description ≤150 chars, output ≤1.5K chars.

| Tool name | Kind | `readOnlyHint` | `untrustedContentHint` | Backing endpoint | Mutates state? | Requires human confirm? |
|---|---|---|---|---|---|---|
| `submit_biz_details` | Declarative `<form>` (no `toolautosubmit`) | n/a | n/a | native form POST + `respondWith()` | yes (direct, human must click Submit per spec) | yes — built into declarative API |
| `submit_fin_details` | Declarative `<form>` (no `toolautosubmit`) | n/a | n/a | native form POST + `respondWith()` | yes (direct, human must click Submit per spec) | yes — built into declarative API |
| `explain_field` | Imperative | `true` | `false` | `GET /api/explain/{field}` | no | no |
| `check_eligibility` | Imperative | `true` | `false` | `POST /api/eligibility/check` | no | no |
| `flag_issues` | Imperative | `true` | `false` | `GET /api/eligibility/flags` | no | no |
| `propose_fields` | Imperative | `false` (explicit) | `false` | `POST /api/form/propose` | yes (uncommitted only) | yes, to commit |
| `extract_doc` | Imperative | `false` (explicit) | **`true`** (returns doc-extracted data) | `POST /api/documents/extract` | yes (uncommitted only) | yes, to commit |
| `save_progress` | Imperative | `false` (explicit) | `false` | `POST /api/form/save` | yes (session only, non-destructive) | no |

The pattern: **`readOnlyHint: true` only on tools that genuinely never write.** Any tool
that writes committed data routes through the human-approval UI, and — critically — the
commit action itself is never a WebMCP tool at all (see next section).

## Sequence: an imperative tool call, end to end

1. Agent discovers tools via `document.modelContext` (browser-native; or explicitly via
   `getTools()` if our own JS ever needs to introspect them)
2. Agent calls e.g. `propose_field_values({ income: "54000", ... })`
3. `webmcp-tools.js`'s `execute()` fires `fetch('/api/form/propose', {...})`
4. FastAPI: `hooks.py` pre-execute hook validates schema + rate limit + logs to `ToolCallLog`
5. `routers/form.py` writes new `FieldValue` rows with `committed=False`
6. Response returns to the tool call; page also updates the DOM to show the diff (or fires
   its own `toolchange`-adjacent UI refresh)
7. Human sees highlighted proposed values in `review.html` (styled via `:tool-form-active`
   where applicable), clicks "Accept" per field or "Accept all"
8. That click hits a **normal, non-WebMCP, authenticated** endpoint that flips
   `committed=True` — deliberately not a WebMCP tool itself, so an agent can never call its
   way into approving its own writes, and deliberately not gated only by `readOnlyHint`
   (an annotation is a *hint* to the agent/harness, not an enforced security boundary —
   see `SECURITY.md`)

## Known WebMCP spec gaps — don't build around assumptions here

These are real, currently-open items in the spec (linked issues in the repo above), not
guesses:

- **No native "confirm before execute" dialog yet.** There's a tracked discussion
  (`requestUserInput` / consequential-action hint, issue #176) about letting the browser
  natively gate risky tools, but it's not shipped. This is exactly why we build our own
  commit/uncommitted pattern rather than relying on a future browser-native prompt.
- **`getTools()` / `executeTool()` exist** and let in-page code discover/invoke tools
  programmatically — but how *declarative* form-tools show up in that list is still TBD.
  Don't build logic that depends on declarative tools appearing there.
- **No native output schema** yet (issue #9) — our tool responses are informally
  JSON-shaped `content` arrays, not validated against a declared output contract.
- **No native streaming tool output** (issue #82) — keep `extract_from_document` responses
  small (return extracted fields, not raw OCR text blobs); this is also a security
  requirement, not just a spec limitation (see `SECURITY.md`).
- **Cross-document tool response is unresolved** (issue #135) — for our declarative forms,
  prefer `SubmitEvent#respondWith()` (no navigation) over letting the form actually
  navigate, since the navigation-response mechanism (`application/ld+json` extraction) is
  still under debate and not something to depend on.
- **Same-origin boundary risk in multi-origin agent browsing** is explicitly flagged in the
  spec's own security self-review as an open, unresolved risk category — not fully
  mitigated by the platform. We don't control this as an app author beyond keeping our own
  `exposedTo` usage minimal (see `SECURITY.md`).

## Deployment

Render, using `render.yaml` to define a single Python web service. No separate frontend
deploy needed since Jinja2 templates are served by the same FastAPI app.