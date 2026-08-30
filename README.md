# PaperPilot

**A WebMCP-powered app where a human and an AI agent fill out complex paperwork together — in the same UI, with the human always in control.**

Built for [The WebMCP Challenge](https://webmcp.devpost.com/) (deadline Sep 3, 2026).

## What this is

PaperPilot is a multi-step application form (mock "Small Business Recovery Grant") that a
person fills out normally through the browser UI — but their AI agent can also read the
form, explain confusing questions, check eligibility, extract data from uploaded documents,
and propose field values, all via **WebMCP tools** registered on the page. Nothing the agent
does is final until the human sees it and confirms it.

## Why WebMCP fits this problem

Bureaucratic forms are exactly the kind of interface that breaks naive AI agents (screenshot +
click simulation) and exactly the kind of interface where blind backend automation is
dangerous (you do NOT want an agent submitting a grant application server-side without the
human seeing the final state). WebMCP's model — tools live in the page, execute against real
page state, and the human watches the same UI the agent is acting on — is a structural fit,
not a bolt-on.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic, SQLModel (SQLite for the hackathon)
- **Frontend:** Jinja2-rendered HTML + vanilla JS (no framework) — WebMCP tools are small
  `fetch()`-based wrappers around FastAPI endpoints
- **Document extraction:** `pdfplumber` / `pytesseract` (or an LLM call) behind a Python endpoint
- **Hosting:** Render (Python-native, free tier, sponsor of this hackathon)

## Document map

Read these in order before writing any code:

1. `INSTRUCTIONS.md` — the standing rules for whichever coding agent (Cursor) builds this repo
2. `ARCHITECTURE.md` — system design, folder layout, data model, API contracts
3. `PHASES.md` — the build plan, phase by phase, with exit criteria for each
4. `SECURITY.md` — WebMCP-specific and general security requirements (read before Phase 2)
5. `HOOKS.md` — dev-workflow hooks + runtime tool-execution hooks
6. `SKILLS.md` — reusable playbooks the agent should apply repeatedly (system design,
   WebMCP tool design, security review)

## Quickstart (once scaffolded)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000` in Chrome with `chrome://flags/#enable-webmcp-testing` enabled,
or in ChatGPT's in-app browser, to test tool registration.