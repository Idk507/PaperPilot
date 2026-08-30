"""Rules engine — pure Python eligibility logic, no FastAPI imports.

Rules (all must pass to be eligible):
  1. annual_revenue  ≤ $5,000,000
  2. employee_count  ≤ 500
  3. revenue_drop_pct ≥ 15%
  4. year_founded    ≤ current_year - 1  (business at least 1 year old)
  5. Consistency: use_of_funds = payroll → employee_count > 0

flag_missing_or_risky() also checks for empty required fields and
data inconsistencies without making a pass/fail determination.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel import Session as DbSession

from app.db import FieldValue

_REQUIRED = [
    "business_name", "business_type", "year_founded", "state",
    "annual_revenue", "employee_count", "revenue_drop_pct",
    "use_of_funds", "applicant_name", "applicant_email",
]


def _committed_values(session_id: str, db: DbSession) -> dict[str, str]:
    rows = db.exec(
        select(FieldValue).where(
            FieldValue.session_id == session_id,
            FieldValue.committed == True,
        )
    ).all()
    return {r.field_name: r.value for r in rows}


def check_eligibility(session_id: str, db: DbSession) -> dict:
    """Return pass/fail and reasons for the given application session.

    Return shape:
      {
        "eligible": bool | None,   # None = insufficient data
        "reasons": [{"field": str, "reason": str, "disqualifying": bool}],
        "ai_summary": str | None,
      }
    """
    values = _committed_values(session_id, db)
    reasons: list[dict] = []

    if not values:
        return {"eligible": None, "reasons": [], "ai_summary": None}

    # Rule 1 — revenue cap
    try:
        revenue = float(values["annual_revenue"])
        if revenue > 5_000_000:
            reasons.append({
                "field": "annual_revenue",
                "reason": f"Annual revenue ${revenue:,.0f} exceeds the $5,000,000 limit.",
                "disqualifying": True,
            })
    except (KeyError, ValueError):
        reasons.append({
            "field": "annual_revenue",
            "reason": "Annual revenue is missing — needed to determine eligibility.",
            "disqualifying": False,
        })

    # Rule 2 — employee cap
    try:
        emp = int(float(values["employee_count"]))
        if emp > 500:
            reasons.append({
                "field": "employee_count",
                "reason": f"{emp} employees exceeds the 500-employee limit.",
                "disqualifying": True,
            })
    except (KeyError, ValueError):
        reasons.append({
            "field": "employee_count",
            "reason": "Employee count is missing.",
            "disqualifying": False,
        })

    # Rule 3 — revenue drop minimum
    try:
        drop = float(values["revenue_drop_pct"])
        if drop < 15:
            reasons.append({
                "field": "revenue_drop_pct",
                "reason": f"Revenue drop {drop:.1f}% is below the 15% minimum required to qualify.",
                "disqualifying": True,
            })
    except (KeyError, ValueError):
        reasons.append({
            "field": "revenue_drop_pct",
            "reason": "Revenue drop percentage is missing.",
            "disqualifying": True,
        })

    # Rule 4 — business age
    try:
        year = int(values["year_founded"])
        current_year = datetime.now(tz=UTC).year
        if year >= current_year:
            reasons.append({
                "field": "year_founded",
                "reason": "Business must be at least 1 year old to qualify.",
                "disqualifying": True,
            })
    except (KeyError, ValueError):
        reasons.append({
            "field": "year_founded",
            "reason": "Year founded is missing.",
            "disqualifying": False,
        })

    # Rule 5 — payroll consistency
    if values.get("use_of_funds") == "payroll":
        try:
            if int(float(values.get("employee_count", "0"))) == 0:
                reasons.append({
                    "field": "employee_count",
                    "reason": "Cannot use grant for payroll with 0 employees.",
                    "disqualifying": True,
                })
        except ValueError:
            pass

    disqualifying = [r for r in reasons if r.get("disqualifying")]

    # Need at least the three financial fields before rendering a verdict
    has_core_data = all(
        k in values for k in ("annual_revenue", "revenue_drop_pct", "employee_count")
    )
    if not has_core_data:
        eligible = None
    else:
        eligible = len(disqualifying) == 0

    # Enrich with AI summary if available
    ai_summary: str | None = None
    try:
        from app.services.ai import summarise_eligibility_with_ai
        ai_summary = summarise_eligibility_with_ai(eligible, reasons, values)
    except Exception:
        pass

    return {"eligible": eligible, "reasons": reasons, "ai_summary": ai_summary}


def flag_missing_or_risky(session_id: str, db: DbSession) -> dict:
    """Return fields that are empty, inconsistent, or likely to cause rejection."""
    values = _committed_values(session_id, db)
    flags: list[dict] = []

    for field in _REQUIRED:
        if not values.get(field, "").strip():
            flags.append({"field": field, "reason": "Required field is empty."})

    # Payroll + 0 employees
    if values.get("use_of_funds") == "payroll":
        try:
            if int(float(values.get("employee_count", "0"))) == 0:
                flags.append({
                    "field": "employee_count",
                    "reason": "Payroll selected as use of funds but employee count is 0.",
                })
        except ValueError:
            pass

    # "other" missing detail
    if (values.get("use_of_funds") == "other"
            and not values.get("use_of_funds_detail", "").strip()):
        flags.append({
            "field": "use_of_funds_detail",
            "reason": "Use of funds is 'Other' but no description provided.",
        })

    # Revenue drop warning (below threshold but not zero)
    try:
        drop = float(values.get("revenue_drop_pct", "100"))
        if 0 < drop < 15:
            flags.append({
                "field": "revenue_drop_pct",
                "reason": f"Revenue drop {drop:.1f}% is below the 15% minimum to qualify.",
            })
    except ValueError:
        pass

    # Revenue above cap
    try:
        rev = float(values.get("annual_revenue", "0"))
        if rev > 5_000_000:
            flags.append({
                "field": "annual_revenue",
                "reason": f"Revenue ${rev:,.0f} exceeds the $5M grant limit.",
            })
    except ValueError:
        pass

    # Very high employee count
    try:
        emp = int(float(values.get("employee_count", "0")))
        if emp > 500:
            flags.append({
                "field": "employee_count",
                "reason": f"{emp} employees exceeds the 500-employee cap.",
            })
    except ValueError:
        pass

    return {"flags": flags, "count": len(flags)}
