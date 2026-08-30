# Testing PaperPilot (human form + WebMCP agent)

This guide covers every surface: the normal browser form, the dashboard, the JSON APIs, and Chrome’s WebMCP Model Context Tool Inspector.

**Do not put API keys in this repo.** Paste a Gemini key only into the Chrome extension settings. If a key was ever pasted into chat or committed, rotate it.

---

## 1. Start the app

From the project root, with the virtualenv:

```powershell
cd C:\Users\dhanu\Downloads\PaperPilot
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**  
Use `127.0.0.1`, not `localhost`, and keep that host consistent so the session cookie sticks.

Automated suite (does not need Chrome):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 2. Human-only path (no agent)

Works in any browser.

| Step | What to do | What you should see |
|---|---|---|
| Home | Fill the pre-qualification widget: revenue `280000`, drop `38`, employees `6` | Green “Likely eligible” + an award range |
| Home | Click **Start Your Application** | Step 1 — Business Info |
| Step 1 | Name `Apex Tech LLC`, type LLC, year `2020`, state CA, EIN `12-3456789` → **Continue** | Step 2. Sidebar completion moves up |
| Step 2 | Revenue `280000`, employees `6`, drop `38`, use of funds Payroll → **Continue** | Step 3. Sidebar shows an award estimate |
| Step 3 | Name, email, check certify → **Review** | Review page with award range + “11 / 11 required” |
| Review | **Submit Application** | Thank-you page with session id |
| Dashboard | Open **/dashboard** any time | Completion ring, eligibility, estimate, checklist, deadline |

**Human Continue must stay a normal HTML form submit.** If you click **Continue to Step 2** yourself and get a JSON error, that is a bug — hard-refresh (`Ctrl+Shift+R`) and try again. The `Unexpected token '<'` error is only for the **agent** tool `submit_biz_details`, not the orange button.

---

## 3. Chrome + WebMCP extension

PaperPilot registers tools on `document.modelContext` (and falls back to `navigator.modelContext`). The Cursor / IDE browser does **not** have WebMCP. You need real Chrome.

### 3.1 One-time Chrome setup

1. Install **Google Chrome** (current stable or Canary if the docs you follow require it).
2. Install the **WebMCP / Model Context Tool Inspector** extension (Chrome Web Store or the challenge’s recommended build).
3. Optional native API: `chrome://flags` → search `webmcp` → enable **WebMCP testing** if the flag exists → relaunch Chrome.
4. Open the extension → paste your **Gemini API key** into its settings only.  
   PaperPilot does **not** use that key. The extension’s Gemini agent is what calls the page tools.

### 3.2 Open the app in that Chrome window

1. Start uvicorn (section 1).
2. In Chrome: **http://127.0.0.1:8000/form/**
3. Open DevTools (`F12`) → Console. You should see:  
   `[PaperPilot] WebMCP detected. Registering tools...`  
   then one line per tool.
4. If you see `WebMCP not available`, the extension/flag is not active on this tab. Reload once. Confirm you are not in an iframe or another browser.

### 3.3 Confirm tools in the Inspector

Open the Inspector side panel. You should see at least:

| Tool | Kind | Needs saved session data? |
|---|---|---|
| `submit_biz_details` | Declarative form (Step 1 only) | No — fills/submits the Step 1 form |
| `submit_fin_details` | Declarative form (Step 2 only) | No — fills/submits the Step 2 form |
| `explain_field` | Imperative, read-only | No |
| `check_eligibility` | Imperative, read-only | Yes — **committed** Step 2 financials |
| `flag_issues` | Imperative, read-only | Yes |
| `get_checklist` | Imperative, read-only | Yes |
| `estimate_award` | Imperative, read-only | Yes — revenue, drop %, employees |
| `propose_fields` | Imperative, write (uncommitted) | Session cookie |
| `save_progress` | Imperative, write | Session cookie |
| `extract_doc` | Imperative, write (uncommitted) | Uploaded doc on Step 3 |

Declarative tools only exist on the page that owns the `<form toolname="...">`.  
`submit_biz_details` is **only on Step 1**. `submit_fin_details` is **only on Step 2**.

---

## 4. Agent test script (copy/paste prompts)

Stay on **http://127.0.0.1:8000/form/step/1** for the first prompt.

### Prompt A — Step 1 submit (this is the one that used to return HTML-as-JSON)

> Submit my business details for Step 1 as Apex Tech LLC, an LLC founded in 2020 in CA with EIN 12-3456789.

Expected tool: `submit_biz_details`  
Expected result (JSON, not HTML):

```json
{
  "ok": true,
  "message": "Business details saved. Stay on this page and call submit_fin_details next if you have financials.",
  "next_tool_hint": "Call submit_fin_details next if you have financials. Do not navigate yet."
}
```

The tab **stays on Step 1** after this tool alone. Intermediate saves do not navigate, so the Inspector can keep calling `submit_fin_details` and `submit_applicant` in the same turn. After `submit_applicant` succeeds, the review page opens a few seconds later.

### Prompt B — Explain a field

> What is an EIN and do I need one?

Expected tool: `explain_field` with `{ "field_name": "ein" }`  
Expected: label, explanation, example, why_asked.

### Prompt C — Propose without committing

> Propose these financials for me to review: annual revenue 280000, 6 employees, 38% revenue drop, use of funds payroll.

Expected tool: `propose_fields`  
Expected: `{ "proposed": ["annual_revenue", ...], "skipped": [] }`  
Values are **not** saved until you Accept them on the Review page.

### Prompt D — After Step 2 is saved (human or `submit_fin_details`)

On Step 2, either fill the form yourself or prompt:

> Submit financials: annual revenue 280000, 6 full-time employees, 38% revenue drop, payroll.

Then:

> Check if I'm eligible, estimate my award, list missing checklist items, flag issues, and save progress.

Expected tools (any order):

- `check_eligibility` → `{ "eligible": true|false|null, "reasons": [...] }`  
  `eligible` is `null` until revenue, drop %, and employee count are **committed**.
- `estimate_award` → `{ "eligible": true, "tier_label": "Mid-tier", "range_low": 16800, "range_high": 28000, ... }`
- `get_checklist` → `completion_pct`, `missing_required`
- `flag_issues` → `{ "flags": [...], "count": N }`
- `save_progress` → `{ "ok": true, "message": "Progress saved." }`

### Prompt E — Document extract (optional)

1. On Step 3, upload a tax-return PDF/PNG.
2. Finish Step 3 to Review, or stay on Review.
3. Prompt: `Extract what you can from my tax return.`
4. Expected: `extract_doc` with `{ "document_type": "tax_return" }`.
5. Review page highlights proposals. **Accept** or **Reject** each one. Submit stays disabled until proposals are resolved.

### Prompt F — One shot (all three saves in one turn)

Hard-refresh (`Ctrl+Shift+R`) so `webmcp-tools.js` is not cached. Stay on **http://127.0.0.1:8000/form/**. Type in the **prompt box**, not the tool dropdown:

> Complete my Small Business Recovery Grant application and save everything. My business is Apex Tech LLC, an LLC founded in 2020 in California, EIN 12-3456789. Annual revenue is $280,000, I have 6 full-time employees, revenue dropped 38%, and I will use the grant for payroll. My name is Jordan Hale, email jordan@apextech.test, and I certify the information is accurate. After you save it, check eligibility, estimate my award, and tell me if anything is still missing.

Expected tools (Gemini often fires them in one parallel batch):

1. `submit_biz_details`
2. `submit_fin_details`
3. `submit_applicant`
4. `check_eligibility` / `estimate_award` / `get_checklist`

The Inspector tab URL **must stay** on Home. Do not reload it mid-prompt. After saves, a bar at the bottom has **Open review** (new tab). Close extra PaperPilot tabs — two tabs register two tool sets (`_0_` and `_1310_`) and cause `Receiving end does not exist`.

If you see `"error": {}` right after the first save, the tab navigated too early and killed the turn. Hard-refresh again.

Address, DBA, and street are **not** form fields. Name + email are required for `submit_applicant`.

---

## 5. Manual tool execution in the Inspector

You can skip Gemini and run one tool at a time.

1. Open Inspector → choose a tool from the dropdown.
2. Arguments:

```json
{}
```

for `check_eligibility`, `flag_issues`, `estimate_award`, `get_checklist`, `save_progress`.

```json
{ "field_name": "ein" }
```

for `explain_field`.

```json
{
  "business_name": "Apex Tech LLC",
  "business_type": "llc",
  "year_founded": 2020,
  "state": "CA",
  "ein": "12-3456789"
}
```

for `propose_fields` (or fill those fields on the Step 1 form and run `submit_biz_details`).

3. Click **Execute Tool**.
4. You want JSON. You do **not** want `Unexpected token '<'` or `invocation failed`.

---

## 6. API smoke test (no Chrome)

With the server running:

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -c @"
import httpx
c = httpx.Client(base_url='http://127.0.0.1:8000', follow_redirects=True)
c.get('/form/')
print('session', dict(c.cookies))
r = c.post('/form/step/1', data={
    'business_name': 'Apex Tech LLC', 'business_type': 'llc',
    'year_founded': '2020', 'state': 'CA', 'ein': '12-3456789',
    'csrf_token': 'skip-if-403'
}, headers={'Accept': 'application/json'})
print('step1 json without csrf', r.status_code, r.text[:160])
"@
```

Better: use the pytest cases `test_step1_agent_json_submit` and the existing form-flow tests.

Session-backed tools (`/api/eligibility/*`, `/api/form/propose`, `/api/form/save`) need the `paperpilot_session` cookie from `GET /form/`.

---

## 7. What each error used to mean

| Symptom | Cause | Fix now |
|---|---|---|
| `Unexpected token '<', "<!DOCTYPE "... is not valid JSON` on `submit_biz_details` | Agent `fetch()` followed a 303 to Step 2 and parsed HTML as JSON | Form POSTs return JSON when `Accept: application/json` |
| `Tool was executed but the invocation failed` on every imperative tool | `execute(_, { signal })` crashed when the Inspector omitted the second argument | Execute handlers no longer destructure a required second argument |
| `eligible: null` / estimate “Incomplete” | Tools read **committed** fields only. `propose_fields` does not commit | Use `submit_biz_details` / `submit_fin_details` or Accept proposals |
| `submit_biz_details` missing on Step 2 | Declarative tool is bound to the Step 1 `<form>` | Imperative copy is registered on other pages; or stay on Step 1 |
| `"error": {}` after the first save | Page navigation aborted the Inspector mid-turn | Steps 1–2 no longer navigate. Hard-refresh `webmcp-tools.js` |
| Page never leaves Home after a full save | Review only opens after `submit_applicant`, with a short delay | Wait ~3s after the last save, or open **/form/review** / **Dashboard** |
| Console: `WebMCP not available` | IDE browser, or Chrome without the extension/flag | Use Chrome with the Inspector |
| Dashboard 500 | Old Jinja bug (`section.items` vs `section['items']`) | Fixed — dashboard should be 200 |
| Extract 404 after upload | Upload stored `tax_return`, extract looked up `tax_return_doc` | Upload and extract now use the same type |

Hard-refresh Chrome after pulling these fixes so `webmcp-tools.js` is not cached.

---

## 8. Suggested 3-minute live demo order

1. Home page + instant screener (no account).
2. Fill Step 1 as a human — prove the form works without AI.
3. Open the Inspector. Ask Gemini Prompt A, then Prompt D after Step 2.
4. Show Dashboard:  completion, eligibility, award range, checklist.
5. On Review: show an agent proposal (yellow) → Accept → Submit.

That sequence is the WebMCP story: the agent calls **named page tools** against **your session**, and the human still owns every commit.
