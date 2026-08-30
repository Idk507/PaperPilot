# SKILLS.md — Reusable Playbooks

These are standing procedures the coding agent should re-apply at multiple points in
`PHASES.md`, not one-time reads. Think of each as a checklist you run *before* touching
code for a given kind of change.

---

## Skill: System Design (run before starting any new phase)

Before writing code for a new feature:

1. **State the user story in one sentence**, from the human's point of view, not the
   agent's. ("As someone filling out the grant form, I want the agent to explain a
   confusing field" — not "the agent needs an explain tool.") If you can't state it this
   way, the feature probably doesn't belong yet.
2. **Identify what already exists that this can reuse.** Per `INSTRUCTIONS.md` rule #4,
   new logic belongs in Python services, not new JS. Check `services/` before writing a
   new endpoint from scratch.
3. **Decide read vs. write before anything else.** Read-only tools skip the
   commit/uncommitted machinery entirely (`ARCHITECTURE.md`). Write tools always go
   through it. Misclassifying this early is the most common architecture mistake in this
   project — decide explicitly, in a comment, before coding.
4. **Draw the sequence** (even just in a code comment) the way `ARCHITECTURE.md`'s
   "Sequence: a tool call, end to end" section does, before implementing. If you can't
   draw it in 5-7 steps, the feature is too big for one phase — split it.
5. **Update `ARCHITECTURE.md`'s tool table in the same commit.** Documentation drift is
   treated as a bug, not cleanup debt.

---

## Skill: WebMCP Tool Design (run before adding any `registerTool` call)

1. **Name it as a verb phrase a non-technical person would recognize**
   (`check_eligibility`, not `elig_v2` or `run`).
2. **Write the description for the agent, not for you.** Describe what it does and when
   to use it, in plain language, the way you'd brief a competent intern who's never seen
   this codebase. Vague descriptions ("handles form stuff") produce unreliable agent
   behavior — this is the #1 cause of a WebMCP demo looking flaky.
3. **`inputSchema` should be as narrow as possible.** Enumerate allowed values
   (`enum: [...]`) wherever the domain is finite instead of accepting free-form strings —
   this both improves agent reliability and closes off the "god tool" risk in
   `SECURITY.md` section 3.
4. **Decide the tool's blast radius before writing `execute()`:**
   - Read-only → no confirmation needed, safe to let the agent call freely
   - Proposes writes → must go through the uncommitted pattern
   - Never: a tool that both writes AND finalizes in the same call
5. **Test it adversarially before considering it done.** Ask: what happens if the agent
   calls this tool with an empty object? A huge string? A field name that doesn't exist?
   The endpoint should fail cleanly (Pydantic 422), not throw a 500 or silently no-op.
6. **One tool, one job.** If a tool's description needs "and" more than once, split it.

---

## Skill: Security Review (run at the end of every phase, per `PHASES.md`)

This is the compressed version of `SECURITY.md` — use it as a fast pass, then do the full
checklist for anything that touches a mutating tool:

1. Can any tool call, on its own, reach a truly final/irreversible state? → must be "no"
2. Is every input to every new endpoint validated server-side, independent of the
   `inputSchema`? → must be "yes"
3. Does any new code path let text from an uploaded document or free-text field get
   echoed back to the agent unsanitized? → must be "no"
4. Are new mutating endpoints covered by the shared hook pipeline in `HOOKS.md`, not a
   bespoke inline check? → must be "yes"
5. Did `exposedTo` get set on anything new without a documented reason? → must be "no"

If any answer is wrong, fix it before moving to the next phase — don't queue it as
"technical debt for after the deadline."

---

## Skill: Demo Storytelling (run once, during Phase 7)

Judges see a <3-minute video and a live URL — they're not required to read your code.
Structure the video to make the architecture legible without narration of internals:

1. 0:00-0:15 — the problem, stated for a real person ("filling out grant paperwork is
   confusing and error-prone")
2. 0:15-0:30 — show the human-only path working, briefly, to establish the baseline
3. 0:30-2:00 — the agent collaboration: explain a field, check eligibility, upload a
   document, show the proposed-values diff, human accepts/rejects
4. 2:00-2:45 — explicitly say what WebMCP made possible that wasn't possible before
   (this directly answers the submission text requirements — write the video script and
   the text description together, from the same notes)
5. 2:45-3:00 — close on the live URL and repo link

Do this before recording, not after — script beats improvisation on a 3-minute cap.