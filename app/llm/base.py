from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

MessageDict = dict[str, Any]


class SamplingParams(BaseModel):
    """采样参数：None 表示使用配置默认值，调用方可按请求覆盖。"""

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None


class ToolCallFunction(BaseModel):
    name: str
    arguments: str = ""


class ToolCall(BaseModel):
    """非流式响应中的工具调用意图（OpenAI function calling 协议）。"""

    id: str
    type: str = "function"
    function: ToolCallFunction


class LLMResponse(BaseModel):
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    tool_calls: list[ToolCall] | None = None

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class ToolCallPart(BaseModel):
    """流式工具调用增量分片（index 用于区分并行工具调用）。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


class StreamEvent(BaseModel):
    """流式事件：content 为增量文本；tool_calls 为工具调用增量；usage/finish_reason 在流末出现。

    usage 用 dict[str, Any] 而非 dict[str, int]：部分供应商会在 usage 里附带
    prompt_tokens_details / completion_tokens_details 等对象字段，严格 int 校验会抛
    ValidationError 导致流中断、已生成内容被丢弃。清洗统一在构造 StreamEvent 前完成。
    """

    content: str = ""
    tool_calls: list[ToolCallPart] = Field(default_factory=list)
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


def clean_usage(usage: dict[str, Any]) -> dict[str, Any]:
    """清洗 usage：仅保留 int 型 token 计数字段，丢弃 *_details 等对象字段。"""
    return {k: v for k, v in usage.items() if isinstance(v, int) and not isinstance(v, bool)}


def log_llm_call(model: str, prompt_tokens: int, completion_tokens: int, latency_ms: int) -> None:
    logger.info(
        "llm_call model=%s prompt_tokens=%s completion_tokens=%s latency_ms=%s",
        model,
        prompt_tokens,
        completion_tokens,
        latency_ms,
    )


class LLMClient(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """非流式补全。tools 为 OpenAI function calling 协议的工具定义。"""

    @abstractmethod
    def stream(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """流式补全，逐事件产出增量内容/工具调用/usage。"""

    async def close(self) -> None:
        """释放底层 HTTP 连接等资源；无状态实现可覆盖为空。"""
        return None


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        if settings.llm_provider == "openai":
            from app.llm.openai_compat import OpenAICompatLLM

            api_credential = settings.llm_api_key
            _llm = OpenAICompatLLM(
                base_url=settings.llm_api_base,
                credential=api_credential,
                model=settings.llm_model,
                timeout=settings.llm_timeout,
            )
        else:
            from app.llm.mock import MockLLM

            _llm = MockLLM()
    return _llm


def set_llm(client: LLMClient | None) -> None:
    global _llm
    _llm = client


def sampling_overrides(sampling: SamplingParams | None) -> dict[str, Any]:
    """合并配置默认值与调用方覆盖值，产出传给供应商的采样参数。"""
    s = sampling or SamplingParams()
    return {
        "temperature": s.temperature if s.temperature is not None else settings.llm_temperature,
        "top_p": s.top_p if s.top_p is not None else settings.llm_top_p,
        "max_tokens": s.max_tokens if s.max_tokens is not None else settings.llm_max_tokens,
        "stop": s.stop if s.stop is not None else settings.llm_stop,
    }
