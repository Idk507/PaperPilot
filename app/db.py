"""SQLModel table definitions, engine, and DB session dependency.

Table name note: FormSession → table "formsession" (SQLModel default).
FieldValue, Document, ToolCallLog keep their default names.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel, create_engine
from sqlmodel import Session as DbSession

from app.settings import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def get_db() -> Generator[DbSession, None, None]:
    """FastAPI dependency that yields a database session."""
    with DbSession(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Table models
# ---------------------------------------------------------------------------


class FormSession(SQLModel, table=True):
    """An applicant's grant application session, keyed by a UUID cookie."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    status: str = Field(default="in_progress")  # in_progress | review | submitted
    current_step: int = Field(default=1)


class FieldValue(SQLModel, table=True):
    """A single field value within a session.

    committed=False rows are agent proposals awaiting human approval.
    Upsert key: (session_id, field_name) — per-field, latest wins.
    There can be at most one committed row and one uncommitted row per field.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    field_name: str
    value: str = Field(default="")
    # human | agent_proposed | document_extracted
    source: str = Field(default="human")
    committed: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class Document(SQLModel, table=True):
    """Metadata for an uploaded supporting document.

    The actual file is stored under UPLOADS_DIR/{session_id}/ and is never
    publicly served — only processed by extraction.py.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    doc_type: str  # tax_return | bank_statement
    original_filename: str
    stored_path: str  # relative to UPLOADS_DIR
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ToolCallLog(SQLModel, table=True):
    """Audit log written by hooks.py for every WebMCP tool call."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    tool_name: str
    input_json: str = Field(default="{}")
    output_json: str = Field(default="{}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    # pending | success | rejected_by_hook | error
    outcome: str = Field(default="pending")
