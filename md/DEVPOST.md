# PaperPilot — Devpost Submission

## Project title
PaperPilot — Human-AI co-pilot for complex grant applications, powered by WebMCP

## Short description (≤160 chars)
A WebMCP-powered grant form where an agent explains, checks eligibility, and proposes
pre-fills — but the human always reviews and confirms before anything is saved.

---

## What it does

PaperPilot is a multi-step "Small Business Recovery Grant" application form. On the
surface it's a normal web form. But when opened in a WebMCP-capable browser, the page
registers 8 tools via `document.modelContext.registerTool()` that let an AI agent work
alongside the applicant — in the same UI, against real page state — without ever
submitting anything on their behalf.

**What the agent can do:**
- `explain_field` — answer "what is an EIN?" right in context
- `check_eligibility` — run the grant's rules engine and explain pass/fail
- `flag_issues` — scan all fields for missing data and inconsistencies
- `propose_fields` — batch-suggest field values for human review
- `save_progress` — checkpoint the session
- `extract_doc` — read an uploaded tax return or bank statement and propose pre-fills
- `submit_biz_details` / `submit_fin_details` — declarative `<form>` tools that trigger
  existing HTML forms (no special JS needed)

**What the agent can never do:**
- Submit the application (requires a human CSRF-protected POST)
- Commit any value without the human clicking "Accept"
- Write `committed=True` to any database row — that invariant is enforced in the backend
  hooks and tested with 96 automated tests

---

## Why WebMCP fits this problem (structural fit, not bolt-on)

Three properties of WebMCP map directly onto the hardest problems with AI-assisted form
filling:

**1. Browser-session auth reuse**
The WebMCP tool calls originate in the same browser tab as the human's session cookie.
There's no OAuth dance, no separate agent login, no API key handed to the LLM. The agent
gets exactly the same authenticated context the human has — nothing more.

**2. The spec's own human-in-the-loop guarantee**
The `toolautosubmit` attribute is deliberately absent from all forms in PaperPilot. Per
the WebMCP spec, without `toolautosubmit`, the agent cannot trigger a form submission —
the human must click the button. This is not an app-level hack; it's a spec-level
property. The app leans on it explicitly.

**3. No blind backend automation**
The alternative — a backend agent that reads the form via screenshot and POSTs values
directly — is exactly what breaks trust in AI-assisted bureaucratic tasks. The human
would have no visibility into what was submitted. With WebMCP, every agent action is
visible in the review UI in real time. The "agent proposed → human accepts/rejects" diff
on the review page is the core demo moment.

---

## How it was implemented

**Both WebMCP APIs are used:**

*Declarative API* — Steps 1 and 2 are standard HTML `<form>` elements annotated with
`toolname`, `tooldescription`, and `toolparamdescription`. The browser synthesizes
`submit_biz_details` and `submit_fin_details` automatically. JavaScript handles
`SubmitEvent.agentInvoked` and calls `event.respondWith()` to return JSON to the agent
without a page navigation.

*Imperative API* — The remaining 6 tools use `document.modelContext.registerTool()` with
explicit `name`, `description`, `inputSchema`, `annotations`, and `execute` function.
Each `execute` makes a `fetch()` to a FastAPI endpoint. The `readOnlyHint` annotation is
set correctly on all 3 read-only tools and `false` on all 3 mutating ones.
`untrustedContentHint: true` is set on `extract_doc` because its output is derived from
user-uploaded documents.

**The uncommitted-values pattern:**

Every agent write goes to a `FieldValue` row with `committed=False`. A separate human-
only endpoint (`POST /form/commit/{field}` with a CSRF token) flips it to `True`. This
is the single most important architectural decision: it makes the human-in-the-loop
guarantee a database constraint, not just a UI pattern.

**The extraction pipeline (Phase 5):**

`pdfplumber` extracts text from PDFs; `pytesseract` handles images. A prompt-injection
guard (`_is_injection()`) scans every extracted candidate before it leaves the extraction
module. Only values that pass the same Pydantic-equivalent validators as human-typed
input are returned. Raw OCR text never reaches the agent.

**Security (Phase 6 — 25 dedicated tests):**
- CSRF tokens (itsdangerous) on all HTML form submissions
- `SameSite=Lax` + `HttpOnly` + `Secure` (prod) session cookies
- `assert_same_origin()` on all JSON API endpoints
- 20-call/60s/session rate limit on every tool-backing endpoint
- `ToolCallLog` audit trail for every tool call

---

## Tech stack

- Python 3.11+, FastAPI, SQLModel (SQLite), Pydantic, Jinja2
- Vanilla JS — no framework; WebMCP tools are small `fetch()` wrappers
- `pdfplumber` / `pytesseract` for document extraction
- Render (Python web service, `render.yaml` included)

---

## What's newly possible with WebMCP

Without WebMCP:
- An agent could only see the form by screenshotting it (fragile, no structured access)
- Any automation would require the agent to have server credentials (dangerous)
- There would be no way to show the human what the agent proposed vs. what was accepted

With WebMCP:
- The agent has structured, typed access to every field's purpose (via `explain_field`)
- The agent can run server-side business logic (eligibility check) with zero credentials
- Proposed values appear as a live diff in the human's UI, accept/reject per field
- Uploaded document extraction is triggered from the browser, not from a separate backend
  agent with file system access

---

## Try it yourself

**Live URL:** https://paperpilot-617103164879.us-central1.run.app

**To test with an agent:**
1. Open Chrome 149+ → `chrome://flags/#enable-webmcp-testing` → Enabled → Relaunch
2. Navigate to the live URL (or `http://localhost:8000` locally)
3. Open Step 1 of the form — your agent now has 8 tools available
4. Ask: *"Can you check if I'm eligible for this grant? And what is an EIN?"*

**Repository:** https://github.com/Idk507paperpilot

---

## Video demo

[Link to demo video — 3 minutes]

Demo covers:
- 0:00 – Human-only path (baseline)
- 0:30 – Agent explains EIN field (`explain_field`)
- 0:55 – Agent checks eligibility (`check_eligibility`)
- 1:20 – Upload tax return → agent extracts and proposes fields (`extract_doc`)
- 1:55 – Review diff: human accepts 3 fields, rejects 1
- 2:20 – What WebMCP made possible (explicit narration)
- 2:50 – Live URL + repo link
