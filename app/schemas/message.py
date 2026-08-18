from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    stream: bool = False
    model: str | None = None
    # 采样参数覆盖（可选）：不传则使用服务端配置默认值
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: list[str] | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tokens: int | None = None
    latency_ms: int | None = None
    model: str | None = None
    finish_reason: str | None = None
    created_at: datetime


class ReplyOut(BaseModel):
    user_message: MessageOut
    assistant_message: MessageOut
