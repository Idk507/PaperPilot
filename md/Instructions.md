# INSTRUCTIONS.md — Standing Rules for the Coding Agent

You are building **PaperPilot**, a WebMCP-powered form-filling app, for a hackathon
deadline. These rules apply to every phase in `PHASES.md`. Read `ARCHITECTURE.md`,
`SECURITY.md`, `HOOKS.md`, and `SKILLS.md` before writing code — they are not optional
background reading, they are load-bearing.

## Source of truth for WebMCP itself

Do not rely on memory or assumption for how the WebMCP API actually works. The
authoritative reference for this project is:

- **https://github.com/Idk507/webmcp** (a fork of the canonical spec repo
  `webmachinelearning/webmcp`) — read `README.md`, `declarative-api-explainer.md`, and
  `security-privacy-questionnaire.md` in that repo before implementing any tool
- Rendered spec: https://webmachinelearning.github.io/webmcp/
- Chrome implementation notes: https://developer.chrome.com/docs/ai/webmcp

If `ARCHITECTURE.md` and the live spec ever disagree, the spec wins and `ARCHITECTURE.md`
should be updated — don't silently code against stale assumptions in either direction.

## Mission

A human fills out a multi-step application form. An AI agent (built into the browser or
ChatGPT) can assist via WebMCP tools registered on the page — both the imperative
(`document.modelContext.registerTool()`) and declarative (`<form toolname=...>`) APIs are
in scope; see `ARCHITECTURE.md` for exactly which tools use which mechanism and why. The
human always sees what the agent proposes before it's committed. Nothing is auto-submitted.

## Non-negotiables

1. **The human-only path must work first and always.** At every phase, someone with no AI
   agent at all must be able to complete and submit the form through the plain UI. WebMCP
   is an enhancement layer, never a dependency.
2. **No silent state changes.** Any tool that changes form data must leave a visible,
   reviewable trace in the UI (see "uncommitted changes" pattern in `ARCHITECTURE.md`).
   Destructive or final actions (e.g., "submit application") require an explicit human
   click on a **non-WebMCP-tool endpoint** — never let a WebMCP tool call itself be the
   final commit or submission. This applies to both imperative tools and declarative
   forms: never add the `toolautosubmit` attribute to a form without a written
   justification recorded in `SECURITY.md`.
3. **All validation happens server-side, in Python.** The `inputSchema` on a WebMCP tool
   (imperative or auto-synthesized from a declarative form) is a hint to the agent, not a
   security boundary. Every FastAPI endpoint backing a tool re-validates with Pydantic
   regardless of what the frontend or the schema already implies. This is explicitly
   called out in the spec's own security self-review — schema conformance is enforced by
   the browser for serialization, not by anyone for business-logic correctness.
4. **`annotations.readOnlyHint` must be truthful.** Only set `readOnlyHint: true` on tools
   that genuinely never write state (see the tool table in `ARCHITECTURE.md`). This is a
   real, spec-defined field that agents/harnesses may use to decide whether to skip a
   confirmation step — mislabeling a mutating tool as read-only is a security bug, not a
   style choice.
5. **Keep JS thin.** Business logic lives in Python. `webmcp-tools.js` should only ever:
   register tools (imperative) or annotate `<form>` elements (declarative), call `fetch()`
   or handle `SubmitEvent#respondWith()` against a FastAPI endpoint, and update the DOM
   with the response. If you find yourself writing more than ~20 lines of actual logic in
   a `.js` file, that logic belongs in Python instead.
6. **Don't invent WebMCP API shape.** Only use APIs documented in the spec repo linked
   above. Concretely, this means: use the real `registerTool()` signature (`name`, `title`,
   `description`, `inputSchema`, `annotations`, `execute`), the real declarative attributes
   (`toolname`, `tooldescription`, `toolparamdescription`, `toolautosubmit`), and the real
   discovery/invocation surface (`getTools()`, `executeTool()`, `toolchange` event). Check
   `ARCHITECTURE.md`'s "Known WebMCP spec gaps" section before assuming an API exists
   (e.g., there is no native output schema, no native streaming, no native confirmation
   dialog as of this writing).
7. **Every tool needs a one-line justification.** Before registering a tool, write in a
   code comment: what human task does this replace or accelerate, and why can't the
   declarative `<form>` tool do it instead? If you can't answer both, don't add the tool —
   judges score tool *quality*, not tool *count*.
8. **Security review is a phase gate, not a final pass.** `SECURITY.md`'s checklist must
   be re-run at the end of every phase in `PHASES.md`, not just once at the end.
9. **Handle registration failures explicitly.** `registerTool()` can throw
   `InvalidStateError`, `NotAllowedError`, `SecurityError`, or `TypeError` (see
   `ARCHITECTURE.md`). `webmcp-tools.js` must catch these and fail visibly in the console
   during development — a silently-failed tool registration is a demo-day risk, not just
   a code smell.

## Definition of Done (applies to every phase)

A phase is not complete until:
- [ ] The human-only path still works with zero regressions
- [ ] Any new tool has a passing manual test in Chrome (`chrome://flags/#enable-webmcp-testing`)
- [ ] Every mutating tool has `readOnlyHint` either correctly unset or explicitly `false`,
      and every non-mutating tool has it `true`
- [ ] No form has `toolautosubmit` without a documented reason in `SECURITY.md`
- [ ] The relevant `HOOKS.md` pre/post-execute checks are wired in, not just documented
- [ ] The `SECURITY.md` checklist for that phase is checked off
- [ ] `README.md`'s Quickstart still boots the app from a clean clone

## Coding conventions

- Python: type-hinted, `ruff` clean, functions under ~40 lines, one FastAPI router per
  domain concern (`routers/eligibility.py`, `routers/documents.py`, etc.)
- Commit style: `phase-N: <what changed>` — keep phases bisectable
- Never commit `.env`, API keys, or uploaded sample documents containing real personal data
- Every new WebMCP tool gets an entry added to `ARCHITECTURE.md`'s tool table — including
  its `readOnlyHint` value — in the same commit that adds the code; the table must never
  drift from reality

## When you're unsure

Stop and re-read `SKILLS.md`'s "system design" skill before adding new architecture.
Don't guess at security posture — `SECURITY.md` is authoritative and was written
specifically to cover gaps most AI coding agents miss (see that file's intro). Don't guess
at WebMCP API shape — go back to the spec repo linked at the top of this file.