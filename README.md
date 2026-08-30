# PaperPilot

**A WebMCP-powered app where a human and an AI agent fill out complex paperwork together — in the same UI, with the human always in control.**

Built for [The WebMCP Challenge](https://webmcp.devpost.com/) (deadline Sep 3, 2026).

---

## What is this?

PaperPilot is a multi-step application form (mock "Small Business Recovery Grant") that a
person fills out normally through the browser UI — but their AI agent can also read the
form, explain confusing questions, check eligibility, extract data from uploaded documents,
and propose field values, all via **WebMCP tools** registered on the page. Nothing the
agent does is final until the human sees it and confirms it.

Bureaucratic forms are exactly the kind of interface that breaks naive AI agents
(screenshot + click simulation) and exactly the kind of interface where blind backend
automation is dangerous. WebMCP's model — tools live in the page, execute against real
page state, and the human watches the same UI the agent is acting on — is a structural
fit, not a bolt-on.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| pip | 23+ | Comes with Python |
| Chrome | 149+ | Required for WebMCP tool registration |
| Tesseract OCR | 5.x | Optional — only needed for image OCR. PDF extraction works without it. Install from [tesseract-ocr.github.io](https://tesseract-ocr.github.io/tessdoc/Installation.html) |

---

## Quickstart (local)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/paperpilot.git
cd paperpilot

# 2. Create virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment (copy the example, then fill in values)
cp .env.example .env
# Edit .env — minimum required: SECRET_KEY

# 5. Run
uvicorn app.main:app --reload
```

Open **http://localhost:8000** in your browser.

---

## Environment variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **Yes** | Random string for CSRF token signing. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `COOKIE_SECURE` | Prod only | Set `true` in production (HTTPS). Default `false` (HTTP dev). |
| `DATABASE_URL` | Optional | SQLite path. Default `sqlite:///./paperpilot.db`. |
| `UPLOADS_DIR` | Optional | Upload storage path. Default `./uploads`. |

Field explanations are static (no cloud LLM). Document extract uses pdfplumber / Tesseract regex. The Chrome Inspector’s Gemini key stays in the extension, not in this app.

---

## Testing with an AI agent

### Enable WebMCP in Chrome

1. Navigate to `chrome://flags/#enable-webmcp-testing`
2. Set the flag to **Enabled**
3. Relaunch Chrome

### Talk to your agent

Once the flag is on and the app is open at `http://localhost:8000/form/`, your agent can use the registered tools. Example prompts:

> "What is an EIN? I'm filling out a grant application."
> → agent calls `explain_field({field_name: "ein"})`

> "Can you check if I'm eligible for this grant?"
> → agent calls `check_eligibility()`

> "I uploaded my tax return. Can you pre-fill what you can from it?"
> → agent calls `extract_doc({document_type: "tax_return"})`

> "Suggest values for the financial section based on what you know about my business."
> → agent calls `propose_fields({annual_revenue: "...", employee_count: "...", ...})`

All agent proposals appear in the review screen as a **diff** — you Accept or Reject each one before anything is saved.

### The 8 registered WebMCP tools

| Tool | Type | What it does |
|---|---|---|
| `submit_biz_details` | Declarative `<form>` | Submits Step 1 (business info) |
| `submit_fin_details` | Declarative `<form>` | Submits Step 2 (financials) |
| `explain_field` | Imperative, read-only | Returns plain-language explanation for any field |
| `check_eligibility` | Imperative, read-only | Runs eligibility rules; returns pass/fail + reason |
| `flag_issues` | Imperative, read-only | Scans all fields for missing data and inconsistencies |
| `propose_fields` | Imperative, mutating | Proposes values for human review (uncommitted until accepted) |
| `save_progress` | Imperative, mutating | Saves session so applicant can resume later |
| `extract_doc` | Imperative, mutating | Reads uploaded PDF/image and proposes extracted field values |

---

## Running tests

```bash
pytest tests/ -v
```

96 tests, covering the full form flow, WebMCP tool endpoints, extraction pipeline, and security checks.

```bash
# Lint
ruff check app/ tests/
```

---

## Architecture in 30 seconds

```
Browser (Chrome + WebMCP flag)
  └── webmcp-tools.js  ←  registers 8 tools via document.modelContext
       ↓ fetch()
FastAPI (Python)
  ├── /form/*           ←  human-facing form flow (CSRF, session cookies)
  ├── /api/form/*       ←  propose_fields, save_progress
  ├── /api/documents/*  ←  extract_doc
  ├── /api/eligibility/ ←  check_eligibility, flag_issues
  └── /api/explain/*    ←  explain_field
       ↓
SQLite (SQLModel)
  ├── FormSession       ←  session state
  ├── FieldValue        ←  committed=True (human) | committed=False (agent pending)
  ├── Document          ←  uploaded file metadata
  └── ToolCallLog       ←  audit trail for every tool call
```

The key invariant: **every agent write is `committed=False`**. The `FieldValue.committed` flag is only flipped to `True` by a human-initiated POST to `/form/commit/{field}` — never by a WebMCP tool call.

---

## Live demo

**Live URL:** https://paperpilot-617103164879.us-central1.run.app *(Google Cloud Run)*

---

## Document map

Read these before contributing:

1. `INSTRUCTIONS.md` — coding agent rules and non-negotiables
2. `ARCHITECTURE.md` — system design, data model, API contracts
3. `PHASES.md` — build plan with exit criteria
4. `SECURITY.md` — WebMCP-specific security requirements (all items `[x]`)
5. `SECURITY_AUDIT.md` — evidence trail for the security checklist
6. `HOOKS.md` — runtime tool-execution hook pipeline
7. `SKILLS.md` — reusable playbooks

---

## License

MIT — see [LICENSE](LICENSE).
