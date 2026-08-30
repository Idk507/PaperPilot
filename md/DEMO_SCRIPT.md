# Demo Script — PaperPilot (3 minutes)

**Format:** screen recording + voiceover. Use Chrome with WebMCP flag enabled.
**URL:** https://paperpilot.onrender.com (or localhost:8000)

---

## 0:00 – 0:15 — The problem

*Show a screenshot of a dense government grant form, then cut to PaperPilot.*

> "Small business grant applications are confusing and error-prone. Missing an EIN
> format, entering the wrong revenue figure, or submitting without checking eligibility
> first can mean rejection. Today I'm going to show you how WebMCP lets an AI agent help
> fill this out — without ever taking the wheel away from the applicant."

---

## 0:15 – 0:30 — Human-only baseline

*Click through the form manually: Step 1 (Business Info) → Step 2 (Financials) → Step 3
(Documents) → Review page. Show that it works completely without an agent.*

> "The form works perfectly as a normal web form. No JavaScript frameworks, no AI
> required. This is the baseline the agent enhances — it never replaces it."

---

## 0:30 – 0:50 — Agent explains a confusing field

*Back to Step 1. Open the agent panel / chat. Ask:*

**Prompt:** "I'm on a grant application form. What is an EIN and do I need one?"

*Agent calls `explain_field({field_name: "ein"})`. Show the structured JSON response in
the agent panel, then the explanation rendered on the page.*

> "The agent calls the `explain_field` tool — a `readOnlyHint: true` imperative tool that
> hits our server-side explanation endpoint. It reads the form's page context without
> any screenshot or DOM scraping. The applicant gets a plain-language answer right in the
> flow."

---

## 0:50 – 1:15 — Agent checks eligibility

*Fill in a few fields (revenue ~$200k, 5 employees, 30% drop, payroll use). Then ask:*

**Prompt:** "Can I check if I qualify for this grant?"

*Agent calls `check_eligibility()`. Show the JSON response — `eligible: true`, reason.*

> "The `check_eligibility` tool runs our server-side rules engine against the current
> session. The agent didn't need database credentials or a special API key — it reused
> the same browser session the applicant already has. That's the structural fit of
> WebMCP."

---

## 1:15 – 1:50 — Extract fields from uploaded document

*Go to Step 3. Upload a sample tax return PDF (or screenshot). Then on the Review page:*

**Click:** "Extract from Tax Return"

*(or via agent:)*  
**Prompt:** "I just uploaded my tax return. Can you pre-fill what you can from it?"

*Agent calls `extract_doc({document_type: "tax_return"})`. Show the review page refreshing
with the diff: 3-4 fields highlighted in yellow with "agent" badge.*

> "The `extract_doc` tool — marked with `untrustedContentHint: true` because it reads
> user-uploaded documents — extracts EIN, revenue, and employee count from the PDF via
> pdfplumber. Critically, raw OCR text never reaches the agent. Only validated field
> values come back."

---

## 1:50 – 2:20 — Human reviews and accepts/rejects proposals

*On the Review page, show the diff clearly. Accept 'annual_revenue' and 'ein'. Reject
'employee_count' (wrong value). Click "Accept All" for the rest.*

> "Every agent proposal lands in this diff view. The human sees exactly what was
> suggested, what the current value is, and can accept or reject field by field. Until
> they click Accept, nothing is saved. This isn't a UI convention — it's enforced in the
> database. Every agent write is `committed=False`. Only a human-initiated POST flips it."

---

## 2:20 – 2:45 — What WebMCP made possible

*Cut to a side-by-side: WebMCP vs. "screenshot agent"*

> "Without WebMCP, an agent helping with this form would need to screenshot the page and
> guess at the field layout — fragile. Or it would need server credentials to write
> directly to the database — dangerous. With WebMCP, the agent has structured, typed
> access to every tool, the same authenticated browser session as the user, and the
> human watches every action in their own UI in real time. The agent is a co-pilot, not
> an autopilot."

---

## 2:45 – 3:00 — Close

*Show the live URL and the GitHub repo link.*

> "PaperPilot — try it at paperpilot.onrender.com, or fork it on GitHub. All 8 WebMCP
> tools, 96 automated tests, and a full security audit. Built for the WebMCP Challenge."

---

## Recording checklist

- [ ] Chrome 149+ with `chrome://flags/#enable-webmcp-testing` enabled
- [ ] Form pre-filled to just before the demo moment in each section
- [ ] Sample tax return PDF ready to upload (see `tests/fixtures/` if added)
- [ ] Agent panel open and visible alongside the form
- [ ] Microphone test before recording
- [ ] Resolution: 1920x1080 minimum; crop to show form + agent panel side by side
- [ ] Keep under 3:00 (Devpost requirement)
