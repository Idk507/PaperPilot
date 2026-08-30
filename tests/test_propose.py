"""Phase 4 — propose_fields + save_progress tool tests.

Covers:
  - POST /api/form/propose creates uncommitted FieldValue rows
  - Committed rows are NOT created by propose
  - POST /api/form/commit/{field} flips committed=True
  - POST /api/form/reject/{field} deletes the uncommitted row
  - Unknown field names are rejected
  - Invalid values are rejected (same validators as human input)
  - Batch propose + bulk commit_all / reject_all
  - Rate limiting (20 calls/min/session)
  - save_progress endpoint
  - hooks.py: committed=True enforcement
"""

from __future__ import annotations

import pytest
from sqlmodel import Session as DbSession
from sqlmodel import select
from starlette.testclient import TestClient

from app.db import FieldValue, engine
from app.main import app
from app.services.hooks import _enforce_no_committed_outputs
from app.services.session_utils import generate_csrf_token


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=True) as c:
        yield c


def _start_session(client: TestClient) -> str:
    client.get("/form/")
    return client.cookies["paperpilot_session"]


# ── Basic propose ────────────────────────────────────────────────────────────

def test_propose_creates_uncommitted_rows(client: TestClient):
    sid = _start_session(client)

    r = client.post("/api/form/propose", json={
        "business_name": "River Coffee",
        "annual_revenue": "250000",
    })
    assert r.status_code == 200
    data = r.json()
    assert "business_name" in data["proposed"]
    assert "annual_revenue" in data["proposed"]
    assert data["skipped"] == []

    # Verify DB: rows must be committed=False
    with DbSession(engine) as db:
        rows = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.committed == False,
            )
        ).all()
        field_names = {r.field_name for r in rows}
        assert "business_name" in field_names
        assert "annual_revenue" in field_names

        # No committed=True rows should exist yet
        committed_rows = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.committed == True,
            )
        ).all()
        assert committed_rows == []


def test_propose_no_session_rejected(client: TestClient):
    r = client.post("/api/form/propose", json={"business_name": "Test"})
    assert r.status_code == 400


def test_propose_unknown_field_skipped(client: TestClient):
    _start_session(client)
    r = client.post("/api/form/propose", json={
        "business_name": "Valid Name",
        "INJECTED_FIELD": "evil value",
    })
    assert r.status_code == 200
    data = r.json()
    assert "business_name" in data["proposed"]
    skipped_fields = [s["field"] for s in data["skipped"]]
    assert "INJECTED_FIELD" in skipped_fields


def test_propose_invalid_value_skipped(client: TestClient):
    _start_session(client)
    r = client.post("/api/form/propose", json={
        "annual_revenue": "-999",          # negative — invalid
        "employee_count": "501",           # exceeds max — still accepted (validation allows, rules flag)
        "revenue_drop_pct": "150",         # > 100 — invalid
        "business_type": "invalid_type",   # not in enum
    })
    assert r.status_code == 200
    data = r.json()
    skipped_fields = [s["field"] for s in data["skipped"]]
    assert "annual_revenue" in skipped_fields
    assert "revenue_drop_pct" in skipped_fields
    assert "business_type" in skipped_fields


def test_propose_source_is_agent_proposed(client: TestClient):
    sid = _start_session(client)
    client.post("/api/form/propose", json={"state": "CA"})

    with DbSession(engine) as db:
        row = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.field_name == "state",
                FieldValue.committed == False,
            )
        ).first()
        assert row is not None
        assert row.source == "agent_proposed"


# ── Commit / reject ───────────────────────────────────────────────────────────

def test_commit_field_flips_committed_true(client: TestClient):
    sid = _start_session(client)
    client.post("/api/form/propose", json={"business_name": "Proposed Name"})

    r = client.post(
        "/form/commit/business_name",
        data={"csrf_token": generate_csrf_token(sid)},
    )
    assert r.status_code == 200

    with DbSession(engine) as db:
        row = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.field_name == "business_name",
                FieldValue.committed == True,
            )
        ).first()
        assert row is not None
        assert row.value == "Proposed Name"


def test_reject_field_deletes_row(client: TestClient):
    sid = _start_session(client)
    client.post("/api/form/propose", json={"state": "TX"})

    r = client.post(
        "/form/reject/state",
        data={"csrf_token": generate_csrf_token(sid)},
    )
    assert r.status_code == 200

    with DbSession(engine) as db:
        row = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.field_name == "state",
                FieldValue.committed == False,
            )
        ).first()
        assert row is None


def test_commit_all_flips_all_proposals(client: TestClient):
    sid = _start_session(client)
    client.post("/api/form/propose", json={
        "business_name": "Bulk Accept Co",
        "annual_revenue": "100000",
        "employee_count": "3",
    })

    r = client.post(
        "/form/commit_all",
        data={"csrf_token": generate_csrf_token(sid)},
    )
    assert r.status_code == 200

    with DbSession(engine) as db:
        uncommitted = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.committed == False,
            )
        ).all()
        assert uncommitted == []


def test_reject_all_deletes_all_proposals(client: TestClient):
    sid = _start_session(client)
    client.post("/api/form/propose", json={
        "business_name": "Reject Me",
        "state": "OR",
    })

    r = client.post(
        "/form/reject_all",
        data={"csrf_token": generate_csrf_token(sid)},
    )
    assert r.status_code == 200

    with DbSession(engine) as db:
        rows = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.committed == False,
            )
        ).all()
        assert rows == []


# ── Security: committed=True cannot come from propose ────────────────────────

def test_propose_never_writes_committed_true(client: TestClient):
    """The propose endpoint must NEVER write committed=True rows."""
    sid = _start_session(client)
    client.post("/api/form/propose", json={
        "business_name": "Security Test",
        "annual_revenue": "500000",
        "employee_count": "10",
        "revenue_drop_pct": "25",
        "use_of_funds": "payroll",
    })

    with DbSession(engine) as db:
        committed = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.committed == True,
            )
        ).all()
        assert committed == [], (
            "propose_fields must NEVER write committed=True rows. "
            f"Found: {[r.field_name for r in committed]}"
        )


def test_hooks_strip_committed_true_from_result():
    """hooks._enforce_no_committed_outputs must strip committed=True from dicts."""
    malicious = {"proposed": ["business_name"], "committed": True}
    cleaned = _enforce_no_committed_outputs(malicious)
    assert "committed" not in cleaned
    assert cleaned["proposed"] == ["business_name"]


def test_hooks_strip_nested_committed_true():
    """Nested committed=True in lists must also be stripped; committed=False is left alone."""
    malicious = {
        "fields": [
            {"field_name": "business_name", "value": "Test", "committed": True},
            {"field_name": "state", "value": "CA", "committed": False},
        ]
    }
    cleaned = _enforce_no_committed_outputs(malicious)
    # The True-committed item must have the key stripped
    assert "committed" not in cleaned["fields"][0]
    # The False-committed item is untouched (committed=False is the expected state)
    assert cleaned["fields"][1].get("committed") is False


# ── CSRF protection on commit/reject ─────────────────────────────────────────

def test_commit_without_csrf_rejected(client: TestClient):
    _start_session(client)
    client.post("/api/form/propose", json={"business_name": "Test"})

    r = client.post(
        "/form/commit/business_name",
        data={"csrf_token": "INVALID_TOKEN"},
    )
    assert r.status_code == 403


def test_reject_without_csrf_rejected(client: TestClient):
    _start_session(client)
    client.post("/api/form/propose", json={"state": "NY"})

    r = client.post(
        "/form/reject/state",
        data={"csrf_token": "BAD_TOKEN"},
    )
    assert r.status_code == 403


# ── save_progress ─────────────────────────────────────────────────────────────

def test_save_progress_returns_ok(client: TestClient):
    _start_session(client)
    r = client.post("/api/form/save")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_save_progress_no_session_rejected(client: TestClient):
    r = client.post("/api/form/save")
    assert r.status_code == 400


# ── Rate limiting (in-memory, resets between TestClient instances) ────────────

def test_rate_limit_enforced():
    """After 20 calls/session the next call returns 429."""
    from app.services import hooks

    # Reset the in-memory rate limit counters for a fresh session
    test_sid = "rate-limit-test-session-xxxx"
    if f"{test_sid}:propose_fields" in hooks._call_log:
        del hooks._call_log[f"{test_sid}:propose_fields"]

    # Exhaust the limit
    for _ in range(20):
        hooks._check_rate_limit(test_sid, "propose_fields")

    # The 21st call must raise
    with pytest.raises(hooks.RateLimitExceeded):
        hooks._check_rate_limit(test_sid, "propose_fields")


def test_submit_step1_json_commits_and_returns_next(client: TestClient):
    _start_session(client)
    r = client.post(
        "/api/form/submit-step/1",
        json={
            "business_name": "Apex Tech LLC",
            "business_type": "llc",
            "year_founded": 2020,
            "state": "CA",
            "ein": "12-3456789",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["saved"] is True

    sid = client.cookies["paperpilot_session"]
    with DbSession(engine) as db:
        row = db.exec(
            select(FieldValue).where(
                FieldValue.session_id == sid,
                FieldValue.field_name == "business_name",
                FieldValue.committed == True,
            )
        ).first()
        assert row is not None
        assert row.value == "Apex Tech LLC"
