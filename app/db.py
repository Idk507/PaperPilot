from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel


class Session(SQLModel, table=True):
    """A single applicant's grant application session."""

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="in_progress")  # "in_progress" | "review" | "submitted"
    current_step: int = Field(default=1)


class FieldValue(SQLModel, table=True):
    """A single field value within a session.

    committed=False rows are agent proposals awaiting human approval.
    committed=True rows are accepted (either human-typed or human-approved agent proposal).
    The upsert key is (session_id, field_name, committed=False) for agent proposals,
    and (session_id, field_name, committed=True) for accepted values — see routers/form.py.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    field_name: str
    value: str = Field(default="")
    # "human" | "agent_proposed" | "agent_committed" | "document_extracted"
    source: str = Field(default="human")
    committed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ToolCallLog(SQLModel, table=True):
    """Audit log for every WebMCP tool call backing endpoint invocation."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    tool_name: str
    input_json: str = Field(default="{}")
    output_json: str = Field(default="{}")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # "pending" | "success" | "rejected_by_hook" | "error"
    outcome: str = Field(default="pending")
