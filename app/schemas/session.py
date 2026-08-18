from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    system_prompt: str | None = None


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=128)
    system_prompt: str | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    system_prompt: str | None
    summary: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
