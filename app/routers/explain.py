"""Explain router — plain-language field explanations for the agent.

Route:
  GET /api/explain/{field_name}

Returns a static dict explanation (hardcoded for reliability).

Security: field_name is validated against an explicit server-side allowlist
before lookup — never reflected back without validation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session as DbSession

from app.db import get_db
from app.services.hooks import RateLimitExceeded, post_execute_hook, pre_execute_hook

router = APIRouter(prefix="/api/explain", tags=["explain"])

# Server-side enum — MUST match inputSchema enum in webmcp-tools.js
_ALLOWED_FIELDS = frozenset([
    "business_name", "business_type", "year_founded", "state", "ein",
    "annual_revenue", "employee_count", "revenue_drop_pct",
    "use_of_funds", "use_of_funds_detail", "tax_return_doc",
    "bank_statement_doc", "applicant_name", "applicant_email", "certify",
])

_EXPLANATIONS: dict[str, dict] = {
    "business_name": {
        "label": "Business Legal Name",
        "explanation": (
            "The full legal name of your business exactly as registered with your state "
            "and as it appears on your tax filings. For sole proprietors this is usually "
            "your personal name or your DBA ('doing business as') name."
        ),
        "example": "Acme Coffee LLC or Jane Smith DBA Jane's Bakery",
        "why_asked": "Used to verify the business in government records and issue the grant check.",
    },
    "business_type": {
        "label": "Business Type",
        "explanation": (
            "The legal structure under which your business operates. Sole proprietors are "
            "unincorporated one-person businesses. LLCs offer liability protection with "
            "tax flexibility. Corporations are formally incorporated entities. Nonprofits "
            "have tax-exempt status."
        ),
        "example": "LLC",
        "why_asked": "Different structures have different documentation requirements.",
    },
    "year_founded": {
        "label": "Year Founded",
        "explanation": (
            "The year your business was officially established or incorporated. For sole "
            "proprietors, this is the year you first started operating. Must be at least "
            "1 year ago to qualify for this grant."
        ),
        "example": "2019",
        "why_asked": "Grant eligibility requires the business to have been operating for at least 1 full year.",
    },
    "state": {
        "label": "State of Registration",
        "explanation": (
            "The US state where your business is legally registered or primarily operates. "
            "Use the two-letter abbreviation. For sole proprietors, this is typically the "
            "state where you live and work."
        ),
        "example": "CA (California)",
        "why_asked": "Determines which state's grant programs may also apply and verifies jurisdiction.",
    },
    "ein": {
        "label": "EIN (Employer Identification Number)",
        "explanation": (
            "A 9-digit federal tax ID issued by the IRS, formatted as XX-XXXXXXX. Also "
            "called a FEIN. Sole proprietors without employees may use their Social "
            "Security Number instead — but many sole proprietors obtain an EIN for privacy. "
            "Leave blank only if you are a sole proprietor with no EIN."
        ),
        "example": "12-3456789",
        "why_asked": "Used to verify your business's tax status with the IRS and issue 1099 forms.",
    },
    "annual_revenue": {
        "label": "Annual Gross Revenue",
        "explanation": (
            "Your total revenue before any deductions, expenses, or taxes for your most "
            "recently completed fiscal year. Enter the number in US dollars without commas "
            "or dollar signs. Maximum $5,000,000 to qualify for this grant."
        ),
        "example": "250000 (for $250,000)",
        "why_asked": "Determines your business's size and grant eligibility tier.",
    },
    "employee_count": {
        "label": "Full-Time Employee Count",
        "explanation": (
            "The number of full-time employees (working 30+ hours per week) on your "
            "payroll as of the application date. Do not include contractors, part-time "
            "workers, or the business owner. Enter 0 if you have no employees. Maximum "
            "500 to qualify."
        ),
        "example": "5",
        "why_asked": "Used to determine grant amount tier and verify eligibility.",
    },
    "revenue_drop_pct": {
        "label": "Revenue Drop Percentage",
        "explanation": (
            "The percentage by which your revenue declined compared to the prior year. "
            "Calculated as: ((prior year revenue - current year revenue) / prior year "
            "revenue) x 100. A minimum 15% drop is required to qualify. Enter a number "
            "between 0 and 100."
        ),
        "example": "35 (meaning a 35% decline)",
        "why_asked": "This grant targets businesses significantly impacted by revenue loss.",
    },
    "use_of_funds": {
        "label": "Primary Use of Funds",
        "explanation": (
            "How you plan to use the grant money. Choose the category that best describes "
            "your primary intended use: payroll (employee wages), rent/utilities (premises "
            "costs), equipment (business tools or machinery), inventory (goods for sale), "
            "or other (describe below)."
        ),
        "example": "payroll",
        "why_asked": "Ensures grant funds are used for qualifying business expenses.",
    },
    "use_of_funds_detail": {
        "label": "Use of Funds Detail",
        "explanation": (
            "Required only if you selected 'Other' as your primary use of funds. Provide "
            "a plain-language description of how you will use the grant money. Maximum "
            "500 characters."
        ),
        "example": "Marketing costs to rebuild customer base after renovation",
        "why_asked": "Needed when 'Other' is selected to verify the expense qualifies.",
    },
    "tax_return_doc": {
        "label": "Tax Return Document",
        "explanation": (
            "Upload your most recent business or personal tax return (if sole proprietor). "
            "Acceptable formats: PDF, PNG, JPEG, or TIFF. Maximum size 10 MB. This is "
            "optional but speeds up verification and may increase your grant amount."
        ),
        "example": "2023_business_tax_return.pdf",
        "why_asked": "Verifies your reported revenue and business legitimacy.",
    },
    "bank_statement_doc": {
        "label": "Bank Statement",
        "explanation": (
            "Upload a recent business bank statement (last 3 months preferred). "
            "Acceptable formats: PDF, PNG, JPEG, or TIFF. Maximum size 10 MB. Optional "
            "but supports your revenue drop claim."
        ),
        "example": "march_2024_statement.pdf",
        "why_asked": "Provides additional evidence of business activity and financial hardship.",
    },
    "applicant_name": {
        "label": "Applicant Full Name",
        "explanation": (
            "Your full legal name as it appears on government-issued ID. This is the "
            "person legally responsible for the application and grant funds. Must match "
            "your tax records."
        ),
        "example": "Jane Marie Smith",
        "why_asked": "Used for identity verification and to make the grant award in your name.",
    },
    "applicant_email": {
        "label": "Applicant Email",
        "explanation": (
            "Your current, working email address. You will receive application status "
            "updates and the grant decision at this address. Use an email you check "
            "regularly."
        ),
        "example": "jane@mybusiness.com",
        "why_asked": "Primary contact method for application status and award notification.",
    },
    "certify": {
        "label": "Certification Checkbox",
        "explanation": (
            "By checking this box you certify under penalty of perjury that all "
            "information in your application is true and accurate to the best of your "
            "knowledge. False statements may result in disqualification and legal "
            "penalties."
        ),
        "example": "Check the box to certify",
        "why_asked": "Required legal certification that the application information is truthful.",
    },
}


@router.get("/{field_name}")
async def explain_field(
    field_name: str,
    request: Request,
    db: DbSession = Depends(get_db),
):
    """Return a plain-language explanation of a grant form field.

    Security: field_name is validated against an explicit server-side allowlist.
    """
    # Server-side allowlist check — mandatory even though inputSchema has an enum
    if field_name not in _ALLOWED_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field '{field_name}'. Must be one of the 15 grant application fields.",
        )

    sid = request.cookies.get("paperpilot_session")
    if sid:
        try:
            log_id = pre_execute_hook(sid, "explain_field", {"field_name": field_name}, db)
        except RateLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
    else:
        log_id = None

    static = _EXPLANATIONS[field_name]
    result = dict(static)
    result["field_name"] = field_name

    if sid and log_id:
        post_execute_hook(log_id, result, "success", db)

    return result
