"""Phase 1 — full human-only form flow tests.

Tests the complete POST-Redirect-GET cycle for all 3 steps,
save/resume, and the submit endpoint.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.session_utils import generate_csrf_token


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=True) as c:
        yield c


# ── Smoke: home + form root ─────────────────────────────────────────────────

def test_home_page(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "PaperPilot" in r.text


def test_form_root_creates_session(client: TestClient):
    r = client.get("/form/")
    assert r.status_code == 200
    assert "paperpilot_session" in r.cookies
    assert "Step 1" in r.text


# ── Step 1 happy path ────────────────────────────────────────────────────────

def test_step1_valid_submit(client: TestClient):
    # Start session
    client.get("/form/")
    sid = client.cookies.get("paperpilot_session")
    assert sid

    r = client.post(
        "/form/step/1",
        data={
            "business_name": "Acme LLC",
            "business_type": "llc",
            "year_founded": "2018",
            "state": "CA",
            "ein": "12-3456789",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    assert r.status_code == 200
    assert "Step 2" in r.text


# ── Step 1 validation errors ────────────────────────────────────────────────

def test_step1_missing_required(client: TestClient):
    client.get("/form/")
    sid = client.cookies.get("paperpilot_session")

    r = client.post(
        "/form/step/1",
        data={
            "business_name": "",
            "business_type": "",
            "year_founded": "",
            "state": "",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    assert r.status_code == 200
    assert "required" in r.text.lower()


def test_step1_invalid_ein(client: TestClient):
    client.get("/form/")
    sid = client.cookies.get("paperpilot_session")

    r = client.post(
        "/form/step/1",
        data={
            "business_name": "Test Co",
            "business_type": "llc",
            "year_founded": "2015",
            "state": "TX",
            "ein": "BADEIN",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    assert r.status_code == 200
    assert "EIN" in r.text


# ── CSRF protection ──────────────────────────────────────────────────────────

def test_step1_csrf_rejected(client: TestClient):
    client.get("/form/")
    r = client.post(
        "/form/step/1",
        data={
            "business_name": "Test",
            "business_type": "llc",
            "year_founded": "2018",
            "state": "CA",
            "csrf_token": "INVALID_TOKEN",
        },
    )
    assert r.status_code == 403


# ── Step 2 happy path ────────────────────────────────────────────────────────

def test_step2_valid_submit(client: TestClient):
    client.get("/form/")
    sid = client.cookies.get("paperpilot_session")

    # Complete step 1 first
    client.post(
        "/form/step/1",
        data={
            "business_name": "Acme Corp",
            "business_type": "corporation",
            "year_founded": "2010",
            "state": "NY",
            "csrf_token": generate_csrf_token(sid),
        },
    )

    r = client.post(
        "/form/step/2",
        data={
            "annual_revenue": "250000",
            "employee_count": "5",
            "revenue_drop_pct": "35",
            "use_of_funds": "payroll",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    assert r.status_code == 200
    assert "Step 3" in r.text


# ── Step 2 validation: use_of_funds=other requires detail ───────────────────

def test_step2_other_requires_detail(client: TestClient):
    client.get("/form/")
    sid = client.cookies.get("paperpilot_session")

    client.post(
        "/form/step/1",
        data={
            "business_name": "Shop",
            "business_type": "sole_proprietor",
            "year_founded": "2019",
            "state": "FL",
            "csrf_token": generate_csrf_token(sid),
        },
    )

    r = client.post(
        "/form/step/2",
        data={
            "annual_revenue": "100000",
            "employee_count": "2",
            "revenue_drop_pct": "20",
            "use_of_funds": "other",
            "use_of_funds_detail": "",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    assert r.status_code == 200
    assert "describe" in r.text.lower()


# ── Full 3-step flow + review ────────────────────────────────────────────────

def _complete_form(client: TestClient) -> str:
    """Helper: complete all 3 steps and return the session ID."""
    client.get("/form/")
    sid = client.cookies["paperpilot_session"]

    client.post(
        "/form/step/1",
        data={
            "business_name": "River Coffee",
            "business_type": "llc",
            "year_founded": "2015",
            "state": "WA",
            "ein": "99-1234567",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    client.post(
        "/form/step/2",
        data={
            "annual_revenue": "180000",
            "employee_count": "4",
            "revenue_drop_pct": "40",
            "use_of_funds": "rent_utilities",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    client.post(
        "/form/step/3",
        data={
            "applicant_name": "Jane Smith",
            "applicant_email": "jane@example.com",
            "certify": "true",
            "csrf_token": generate_csrf_token(sid),
        },
    )
    return sid


def test_review_page_shows_all_fields(client: TestClient):
    sid = _complete_form(client)
    r = client.get("/form/review")
    assert r.status_code == 200
    assert "River Coffee" in r.text
    assert "Jane Smith" in r.text
    assert "jane@example.com" in r.text


def test_submit_completes(client: TestClient):
    sid = _complete_form(client)
    r = client.post(
        "/form/submit",
        data={"csrf_token": generate_csrf_token(sid)},
    )
    assert r.status_code == 200
    assert "Submitted" in r.text or "submitted" in r.text.lower()


def test_submit_blocked_when_already_submitted(client: TestClient):
    sid = _complete_form(client)
    client.post("/form/submit", data={"csrf_token": generate_csrf_token(sid)})
    r = client.post("/form/submit", data={"csrf_token": generate_csrf_token(sid)})
    assert r.status_code == 400


# ── Resume: revisiting /form/ after partial completion ──────────────────────

def test_resume_shows_correct_step(client: TestClient):
    client.get("/form/")
    sid = client.cookies["paperpilot_session"]

    client.post(
        "/form/step/1",
        data={
            "business_name": "Resume Test",
            "business_type": "nonprofit",
            "year_founded": "2012",
            "state": "OR",
            "csrf_token": generate_csrf_token(sid),
        },
    )

    # GET /form/ should now show step 2 (current_step was advanced)
    r = client.get("/form/")
    assert r.status_code == 200
    assert "Step 2" in r.text or "Financial" in r.text

    # Previously saved value should be pre-filled
    r2 = client.get("/form/step/1")
    assert "Resume Test" in r2.text

