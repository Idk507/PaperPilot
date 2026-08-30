"""Pydantic request/response schemas (separate from SQLModel table definitions).

These are the API contracts between the frontend JS and FastAPI endpoints.
Business logic lives in services/, not here.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Form / session schemas
# ---------------------------------------------------------------------------


class SessionOut(BaseModel):
    id: str
    status: str
    current_step: int


class FieldValueIn(BaseModel):
    """Single field value submitted by the human via a form step POST."""

    field_name: str
    value: str


class ProposeFieldsIn(BaseModel):
    """Payload for the propose_fields WebMCP tool endpoint.

    Only fields explicitly listed here are accepted — no additionalProperties.
    Server-side validation re-checks every value through field-specific validators
    in routers/form.py regardless of what this schema says.
    """

    business_name: str | None = Field(default=None, max_length=200)
    business_type: str | None = Field(default=None)
    year_founded: int | None = Field(default=None, ge=1800, le=2100)
    state: str | None = Field(default=None)
    ein: str | None = Field(default=None)
    annual_revenue: float | None = Field(default=None, ge=0)
    employee_count: int | None = Field(default=None, ge=0)
    revenue_drop_pct: float | None = Field(default=None, ge=0, le=100)
    use_of_funds: str | None = Field(default=None)
    use_of_funds_detail: str | None = Field(default=None, max_length=500)
    applicant_name: str | None = Field(default=None, max_length=200)
    applicant_email: EmailStr | None = Field(default=None)


class ProposeFieldsOut(BaseModel):
    proposed: list[str]
    message: str


class CommitFieldIn(BaseModel):
    field_name: str


# ---------------------------------------------------------------------------
# Eligibility schemas
# ---------------------------------------------------------------------------


class EligibilityReason(BaseModel):
    field: str
    reason: str


class EligibilityOut(BaseModel):
    eligible: bool | None
    reasons: list[EligibilityReason]


class FlagOut(BaseModel):
    flags: list[EligibilityReason]


# ---------------------------------------------------------------------------
# Explain schema
# ---------------------------------------------------------------------------


ALLOWED_FIELDS = [
    "business_name",
    "business_type",
    "year_founded",
    "state",
    "ein",
    "annual_revenue",
    "employee_count",
    "revenue_drop_pct",
    "use_of_funds",
    "use_of_funds_detail",
    "tax_return_doc",
    "bank_statement_doc",
    "applicant_name",
    "applicant_email",
    "certify",
]


class ExplainOut(BaseModel):
    field_name: str
    label: str
    explanation: str
    example: str


# ---------------------------------------------------------------------------
# Document extraction schemas
# ---------------------------------------------------------------------------


class ExtractDocIn(BaseModel):
    document_type: str = Field(..., pattern="^(tax_return|bank_statement)$")


class ExtractDocOut(BaseModel):
    proposed: dict[str, str]
    skipped: list[str]
    message: str


# ---------------------------------------------------------------------------
# Audit schemas
# ---------------------------------------------------------------------------


class AuditLogIn(BaseModel):
    tool_name: str
    input_json: str = Field(default="{}")
    outcome: str = Field(default="success")
