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
            FieldValue.committed.is_(True),
        )
    ).all()
    return {r.field_name: r.value for r in rows}


def check_eligibility(session_id: str, db: DbSession) -> dict:
    """Return pass/fail and reasons for the given application session.

    Return shape:
      {
        "eligible": bool | None,   # None = insufficient data
        "reasons": [{"field": str, "reason": str, "disqualifying": bool}],
      }
    """
    values = _committed_values(session_id, db)
    reasons: list[dict] = []

    if not values:
        return {"eligible": None, "reasons": []}

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

    return {"eligible": eligible, "reasons": reasons}


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


# ─── Award Estimate ──────────────────────────────────────────────────────────

_TIER_TABLE = [
    (50, 50_000, "High-impact"),
    (30, 25_000, "Mid-tier"),
    (15, 10_000, "Base"),
]


def calculate_award_estimate(
    annual_revenue: float | None,
    revenue_drop_pct: float | None,
    employee_count: int | None,
) -> dict:
    """Return a tiered award estimate based on eligibility inputs.

    Returns:
        {
          "eligible": bool,
          "tier_label": str,
          "base_amount": int,
          "employee_bonus": int,
          "max_award": int,
          "range_low": int,
          "range_high": int,
          "notes": list[str],
        }
    """
    notes: list[str] = []

    if revenue_drop_pct is None or annual_revenue is None or employee_count is None:
        return {
            "eligible": None,
            "tier_label": "Incomplete",
            "base_amount": 0,
            "employee_bonus": 0,
            "max_award": 0,
            "range_low": 0,
            "range_high": 0,
            "notes": ["Fill in annual revenue, revenue drop %, and employee count to see your estimate."],
        }

    if annual_revenue > 5_000_000:
        return {
            "eligible": False,
            "tier_label": "Ineligible",
            "base_amount": 0,
            "employee_bonus": 0,
            "max_award": 0,
            "range_low": 0,
            "range_high": 0,
            "notes": ["Annual revenue exceeds the $5M cap."],
        }

    if revenue_drop_pct < 15:
        return {
            "eligible": False,
            "tier_label": "Ineligible",
            "base_amount": 0,
            "employee_bonus": 0,
            "max_award": 0,
            "range_low": 0,
            "range_high": 0,
            "notes": [f"Revenue drop of {revenue_drop_pct:.1f}% is below the 15% minimum."],
        }

    if employee_count > 500:
        return {
            "eligible": False,
            "tier_label": "Ineligible",
            "base_amount": 0,
            "employee_bonus": 0,
            "max_award": 0,
            "range_low": 0,
            "range_high": 0,
            "notes": [f"Employee count of {employee_count} exceeds the 500-employee cap."],
        }

    # Determine tier from revenue drop
    base_amount = _TIER_TABLE[-1][1]
    tier_label = _TIER_TABLE[-1][2]
    for threshold, amount, label in _TIER_TABLE:
        if revenue_drop_pct >= threshold:
            base_amount = amount
            tier_label = label
            notes.append(f"{revenue_drop_pct:.0f}% revenue drop qualifies for the {label} tier.")
            break

    # Employee bonus: $500 per employee, max $10,000
    employee_bonus = min(employee_count * 500, 10_000)
    if employee_bonus > 0:
        notes.append(f"{employee_count} employees adds up to ${employee_bonus:,} in workforce support bonus.")

    max_award = base_amount + employee_bonus
    range_low = int(max_award * 0.6)
    range_high = max_award
    notes.append("Final award determined by program reviewers after verification.")

    return {
        "eligible": True,
        "tier_label": tier_label,
        "base_amount": base_amount,
        "employee_bonus": employee_bonus,
        "max_award": max_award,
        "range_low": range_low,
        "range_high": range_high,
        "notes": notes,
    }


def get_application_checklist(session_id: str, db: DbSession) -> dict:
    """Return a structured checklist of all required fields and their status."""
    values = _committed_values(session_id, db)

    sections = [
        {
            "title": "Step 1 — Business Info",
            "fields": [
                ("business_name",    "Business Legal Name",   True),
                ("business_type",    "Business Type",         True),
                ("year_founded",     "Year Founded",          True),
                ("state",            "State of Registration", True),
                ("ein",              "EIN",                   False),
            ],
        },
        {
            "title": "Step 2 — Financial Info",
            "fields": [
                ("annual_revenue",      "Annual Gross Revenue",  True),
                ("employee_count",      "Full-Time Employees",   True),
                ("revenue_drop_pct",    "Revenue Drop (%)",      True),
                ("use_of_funds",        "Primary Use of Funds",  True),
                ("use_of_funds_detail", "Use of Funds Detail",   False),
            ],
        },
        {
            "title": "Step 3 — Applicant",
            "fields": [
                ("applicant_name",  "Full Name",     True),
                ("applicant_email", "Email Address", True),
                ("certify",         "Certification", True),
            ],
        },
    ]

    total_required = 0
    total_filled   = 0
    checklist_sections = []

    for section in sections:
        items = []
        for field_key, label, required in section["fields"]:
            filled = bool(values.get(field_key, "").strip())
            if required:
                total_required += 1
                if filled:
                    total_filled += 1
            items.append({
                "field":    field_key,
                "label":    label,
                "required": required,
                "filled":   filled,
                "value":    values.get(field_key, ""),
            })
        checklist_sections.append({"title": section["title"], "items": items})

    completion_pct = int((total_filled / total_required * 100) if total_required else 0)

    missing_required = [
        item["label"]
        for section in checklist_sections
        for item in section["items"]
        if item["required"] and not item["filled"]
    ]

    return {
        "sections":        checklist_sections,
        "total_required":  total_required,
        "total_filled":    total_filled,
        "completion_pct":  completion_pct,
        "missing_required": missing_required,
    }
