"""Phase 3 — eligibility rules engine + API tests.

Covers every disqualifying rule and the happy path.
Also verifies read-only guarantee (no FieldValue rows written by check/flags).
"""

from __future__ import annotations

import pytest
from sqlmodel import Session as DbSession, SQLModel, create_engine
from starlette.testclient import TestClient

from app.db import FieldValue, FormSession, engine
from app.main import app
from app.services.rules_engine import check_eligibility, flag_missing_or_risky
from app.services.session_utils import generate_csrf_token


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app, follow_redirects=True) as c:
        yield c


@pytest.fixture
def db_session():
    """Yield a database session using the real app engine."""
    with DbSession(engine) as session:
        yield session


def _make_session(db: DbSession) -> FormSession:
    """Create a FormSession and return it."""
    sess = FormSession()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def _set_fields(session_id: str, fields: dict, db: DbSession):
    """Upsert committed FieldValue rows for a session."""
    for field_name, value in fields.items():
        existing = db.exec(
            __import__("sqlmodel", fromlist=["select"]).select(FieldValue).where(
                FieldValue.session_id == session_id,
                FieldValue.field_name == field_name,
                FieldValue.committed == True,  # noqa: E712
            )
        ).first()
        if existing:
            existing.value = str(value)
            db.add(existing)
        else:
            db.add(FieldValue(
                session_id=session_id,
                field_name=field_name,
                value=str(value),
                source="human",
                committed=True,
            ))
    db.commit()


ELIGIBLE_FIELDS = {
    "business_name": "River Coffee",
    "business_type": "llc",
    "year_founded": "2018",
    "state": "CA",
    "annual_revenue": "200000",
    "employee_count": "4",
    "revenue_drop_pct": "35",
    "use_of_funds": "payroll",
    "applicant_name": "Jane Smith",
    "applicant_email": "jane@example.com",
}


# ── Unit tests: rules_engine ──────────────────────────────────────────────

def test_eligible_happy_path(db_session):
    sess = _make_session(db_session)
    _set_fields(sess.id, ELIGIBLE_FIELDS, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is True
    disqualifying = [r for r in result["reasons"] if r.get("disqualifying")]
    assert disqualifying == []


def test_disqualified_revenue_too_high(db_session):
    sess = _make_session(db_session)
    fields = {**ELIGIBLE_FIELDS, "annual_revenue": "6000000"}
    _set_fields(sess.id, fields, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is False
    fields_flagged = [r["field"] for r in result["reasons"] if r.get("disqualifying")]
    assert "annual_revenue" in fields_flagged


def test_disqualified_too_many_employees(db_session):
    sess = _make_session(db_session)
    fields = {**ELIGIBLE_FIELDS, "employee_count": "501"}
    _set_fields(sess.id, fields, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is False
    fields_flagged = [r["field"] for r in result["reasons"] if r.get("disqualifying")]
    assert "employee_count" in fields_flagged


def test_disqualified_revenue_drop_too_low(db_session):
    sess = _make_session(db_session)
    fields = {**ELIGIBLE_FIELDS, "revenue_drop_pct": "10"}
    _set_fields(sess.id, fields, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is False
    fields_flagged = [r["field"] for r in result["reasons"] if r.get("disqualifying")]
    assert "revenue_drop_pct" in fields_flagged


def test_disqualified_business_too_new(db_session):
    from datetime import UTC, datetime
    sess = _make_session(db_session)
    current_year = str(datetime.now(tz=UTC).year)
    fields = {**ELIGIBLE_FIELDS, "year_founded": current_year}
    _set_fields(sess.id, fields, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is False
    fields_flagged = [r["field"] for r in result["reasons"] if r.get("disqualifying")]
    assert "year_founded" in fields_flagged


def test_disqualified_payroll_with_zero_employees(db_session):
    sess = _make_session(db_session)
    fields = {**ELIGIBLE_FIELDS, "use_of_funds": "payroll", "employee_count": "0"}
    _set_fields(sess.id, fields, db_session)

    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is False


def test_no_data_returns_none_eligible(db_session):
    sess = _make_session(db_session)
    result = check_eligibility(sess.id, db_session)
    assert result["eligible"] is None


def test_flags_missing_required_fields(db_session):
    sess = _make_session(db_session)
    result = flag_missing_or_risky(sess.id, db_session)
    # All required fields missing → flags count > 0
    assert result["count"] > 0
    flagged_fields = [f["field"] for f in result["flags"]]
    assert "annual_revenue" in flagged_fields
    assert "employee_count" in flagged_fields


def test_flags_inconsistency_payroll_zero_employees(db_session):
    sess = _make_session(db_session)
    fields = {**ELIGIBLE_FIELDS, "use_of_funds": "payroll", "employee_count": "0"}
    _set_fields(sess.id, fields, db_session)

    result = flag_missing_or_risky(sess.id, db_session)
    reasons = [f["reason"] for f in result["flags"]]
    assert any("payroll" in r.lower() for r in reasons)


# ── API tests: eligibility endpoints ────────────────────────────────────────

def _complete_step1(client: TestClient, sid: str):
    client.post("/form/step/1", data={
        "business_name": "Test Biz",
        "business_type": "llc",
        "year_founded": "2018",
        "state": "CA",
        "csrf_token": generate_csrf_token(sid),
    })


def _complete_step2(client: TestClient, sid: str, revenue="200000", drop="35", emp="4"):
    client.post("/form/step/2", data={
        "annual_revenue": revenue,
        "employee_count": emp,
        "revenue_drop_pct": drop,
        "use_of_funds": "payroll",
        "csrf_token": generate_csrf_token(sid),
    })


def test_eligibility_check_endpoint_eligible(client: TestClient):
    client.get("/form/")
    sid = client.cookies["paperpilot_session"]
    _complete_step1(client, sid)
    _complete_step2(client, sid)

    r = client.post("/api/eligibility/check")
    assert r.status_code == 200
    data = r.json()
    assert "eligible" in data
    assert data["eligible"] is True


def test_eligibility_check_endpoint_ineligible(client: TestClient):
    client.get("/form/")
    sid = client.cookies["paperpilot_session"]
    _complete_step1(client, sid)
    _complete_step2(client, sid, revenue="9000000")  # too high

    r = client.post("/api/eligibility/check")
    assert r.status_code == 200
    data = r.json()
    assert data["eligible"] is False


def test_eligibility_check_no_session(client: TestClient):
    r = client.post("/api/eligibility/check")
    assert r.status_code == 400


def test_flags_endpoint_returns_flags(client: TestClient):
    client.get("/form/")
    r = client.get("/api/eligibility/flags")
    assert r.status_code == 200
    data = r.json()
    assert "flags" in data


# ── Security: read-only guarantee ────────────────────────────────────────────

def test_check_eligibility_writes_no_field_values(db_session):
    """check_eligibility must not write any FieldValue rows."""
    from sqlmodel import select

    sess = _make_session(db_session)
    _set_fields(sess.id, ELIGIBLE_FIELDS, db_session)

    before = db_session.exec(
        select(FieldValue).where(FieldValue.session_id == sess.id)
    ).all()
    before_count = len(before)

    check_eligibility(sess.id, db_session)
    flag_missing_or_risky(sess.id, db_session)

    after = db_session.exec(
        select(FieldValue).where(FieldValue.session_id == sess.id)
    ).all()
    assert len(after) == before_count, "Eligibility check must not write FieldValue rows."


# ── explain endpoint ──────────────────────────────────────────────────────────

def test_explain_valid_field(client: TestClient):
    r = client.get("/api/explain/ein")
    assert r.status_code == 200
    data = r.json()
    assert data["field_name"] == "ein"
    assert "explanation" in data
    assert len(data["explanation"]) > 10


def test_explain_invalid_field_rejected(client: TestClient):
    r = client.get("/api/explain/secret_injected_field")
    assert r.status_code == 400
