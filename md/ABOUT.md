## Inspiration

Grant websites are where AI agents usually fail in public: they screenshot buttons, guess at labels, and sometimes submit data the applicant never saw. Paperwork is also where **trust** matters more than speed. We were inspired by a simple mismatch: people already talk to an assistant in a side panel, but the form in the main tab has no structured way to let that assistant help _without_ taking the wheel.

[WebMCP](https://github.com/webmachinelearning/webmcp) is the missing joint. Tools live **in the page**, run against the **same session cookie** as the human, and the applicant watches the same UI. We chose a mock Small Business Recovery Grant because that domain has real rules (revenue caps, headcount, documented drop in sales) and jargon (EIN, use of funds) that people actually ask about.

We wanted a demo where the impressive part is not “the model filled 11 fields.” It is: the model **cannot** silently commit those fields.

## What it does

PaperPilot is a three-step grant application (business → financials → applicant) plus review, a dashboard, and a home-page pre-qualification widget. In a normal browser it is a FastAPI + Jinja form. In Chrome with WebMCP (flag or Model Context Tool Inspector), the page registers tools such as `explain_field`, `check_eligibility`, `flag_issues`, `propose_fields`, `extract_doc`, and step save tools.

Eligibility is a **rules engine**, not a vibe check. A business qualifies when revenue is at most \(\$5{,}000{,}000\), headcount is at most \(500\), and year-over-year revenue drop \(d\) satisfies \(d \geq 15\).

Award estimate is tiered on that drop, plus a workforce bonus:

$$
B(d) =
\begin{cases}
50000 & d \geq 50 \\
25000 & d \geq 30 \\
10000 & d \geq 15 \\
0 & \text{otherwise}
\end{cases}
\qquad
A = B(d) + \min(500 e,\, 10000)
$$

where \(e\) is full-time employees. The UI shows a range (about \(0.6A\) to \(A\)) because reviewers still decide the final amount.

Agent proposals write `FieldValue` rows with `committed=False`. Only a human CSRF POST can flip `committed=True`. Final **Submit application** is never a WebMCP tool.

**Try it:** [live demo](https://paperpilot-617103164879.us-central1.run.app) · [source on GitHub](https://github.com/Idk507/PaperPilot)

## How we built it

**Stack:** Python 3.11, FastAPI, SQLModel/SQLite, Jinja2, and vanilla JS in `webmcp-tools.js`. No React. Document extract uses `pdfplumber` and optional Tesseract; candidates pass the same validators as typed input, plus an injection-phrase filter. Raw OCR never goes back to the agent.

**Two WebMCP surfaces:**

- _Declarative_ — Step 1 and 2 use `<form toolname="...">` so the browser synthesizes `submit_biz_details` / `submit_fin_details`.
- _Imperative_ — `document.modelContext.registerTool()` for explain, eligibility, flags, checklist, estimate, propose, extract, save, and applicant save.

Each `execute` is a same-origin `fetch()` to `/api/...`. JSON is returned when `Accept: application/json` so the agent does not parse a `303` HTML body. Humans still get HTML redirects.

**Security we actually shipped:** HttpOnly `SameSite=Lax` cookies, `COOKIE_SECURE` on HTTPS, CSRF on HTML posts, `assert_same_origin()` on mutating JSON APIs, 20 calls / 60s / session / tool, and `ToolCallLog` audit rows. There is **no** app-side LLM API key. The Inspector’s Gemini key stays in Chrome.

**Deploy:** Docker (Python slim + `tesseract-ocr`) on **Google Cloud Run**, with `SECRET_KEY` in Secret Manager.

## Challenges we ran into

**1. Navigation vs. the Inspector.** Saving Step 1 with `window.location.href` (or `history.pushState`) aborted the agent mid-turn: tools vanished, Chrome sometimes died with `RESULT_CODE_KILLED_BAD_MESSAGE`, and traces showed `"error": {}`. A full-page iframe “preview” was worse: the iframe registered a **second** copy of every tool and the extension returned _Could not establish connection. Receiving end does not exist._ The fix was boring and correct: **do not change this tab’s URL during a tool turn.** Saves return JSON; the human opens Review in a new tab.

**2. HTML mistaken for JSON.** Agent `fetch()` followed the human `303` and tried to `JSON.parse("<!DOCTYPE html>")`. We split responses on `Accept`.

**3. Human-in-the-loop as data, not copy.** It is easy to _say_ “the user confirms.” It is harder to make `committed=True` unreachable from every tool path. Hooks plus tests are what we trust.

**4. Cloud LLMs in the form backend.** We started with optional Azure OpenAI for explanations, then removed it. Grant copy should be deterministic; extract should be regex/OCR + validators. The _agent_ can still be Gemini in the browser. That split kept deploy simple and keys out of Cloud Run.

**5. Ephemeral SQLite on Cloud Run.** Fine for a hackathon demo; a real program would need Cloud SQL. We documented it instead of pretending persistence.

## Accomplishments that we're proud of

- A working WebMCP grant form on Cloud Run that a Chrome Inspector agent can drive with one prompt — explain, eligibility, estimate, checklist, and propose/save — while the applicant still owns commit.
- Both declarative `<form>` tools and imperative `registerTool()` on the same session.
- The uncommitted-values pattern: agents write drafts; only a human CSRF POST commits.
- Ninety-nine automated tests around validators, rules, hooks, and API contracts.

## What we learned

WebMCP is not “ChatGPT that can click.” It is **capability discovery on a document**: schemas, `readOnlyHint`, no `toolautosubmit` unless you mean it. The hard product problem is **lifecycle** — what happens to `modelContext` when the document navigates.

We also learned to treat the Inspector like a second user with a fragile connection: one tab, no reload mid-prompt, tools registered once.

On the domain side, eligibility is just a few inequalities, but applicants experience them as anxiety. Showing \(A\) as a **range**, plus a checklist of 11 required fields, made the demo feel like a grant site instead of a toy CRUD form.

## What's next for PaperPilot

- Persist sessions (Cloud SQL) and uploads (GCS) if this left the demo stage.
- More programs as data (same tools, different rules files).
- Keep the invariant: agents propose; humans commit.
