from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    type: Literal["summarize", "translate", "echo"]
    payload: dict[str, Any] = Field(min_length=1)
    priority: int = Field(default=5, ge=1, le=10)
    session_id: int | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    session_id: int | None
    type: str
    status: str
    priority: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    retry_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
