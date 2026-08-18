from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import settings
from app.llm.base import (
    LLMClient,
    LLMResponse,
    MessageDict,
    SamplingParams,
    StreamEvent,
    ToolCall,
    ToolCallFunction,
    log_llm_call,
)


def _count_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MockLLM(LLMClient):
    """无外部依赖的确定性 LLM，用于本地开发与测试。

    当传入 tools 且用户消息命中工具触发词（天气/时间/计算）且尚无工具结果时，
    模拟模型返回一次 tool_calls（finish_reason=tool_calls）；否则返回文本，以便
    无真实 API 也能演示完整工具调用链路。
    """

    def _tool_intent(self, messages: list[MessageDict]) -> list[ToolCall] | None:
        if any(m.get("role") == "tool" for m in messages):
            return None  # 已有工具结果，进入最终回答
        last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not last_user:
            return None
        text = str(last_user.get("content", ""))
        if "天气" in text:
            return [self._tc("get_weather", {"city": "北京"})]
        if "时间" in text:
            return [self._tc("get_current_time", {})]
        m = re.search(r"(\d[\d\s+\-*/().]*\d)", text)
        if "计算" in text and m:
            return [self._tc("calculate", {"expression": m.group(1).strip()})]
        return None

    @staticmethod
    def _tc(name: str, args: dict[str, Any]) -> ToolCall:
        return ToolCall(
            id=f"call_mock_{name}",
            type="function",
            function=ToolCallFunction(name=name, arguments=json.dumps(args, ensure_ascii=False)),
        )

    def _compose(self, messages: list[MessageDict]) -> str:
        tool_msg = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        if tool_msg:
            return f"根据工具返回：{str(tool_msg.get('content', ''))[:120]}"
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if "摘要" in system:
            return f"摘要：{last_user[:80]}"
        if "翻译" in system:
            return f"[mock-translate] {last_user[:100]}"
        return f"[mock:{settings.llm_model}] 收到请求：{last_user[:100]}"

    async def complete(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        start = time.perf_counter()
        if settings.llm_mock_delay:
            await asyncio.sleep(settings.llm_mock_delay)
        if tools:
            intent = self._tool_intent(messages)
            if intent:
                return LLMResponse(
                    content="",
                    model=model or settings.llm_model,
                    prompt_tokens=_count_tokens("".join(str(m.get("content", "")) for m in messages)),
                    completion_tokens=0,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    finish_reason="tool_calls",
                    tool_calls=intent,
                )
        content = self._compose(messages)
        prompt_text = "".join(str(m.get("content", "")) for m in messages)
        latency_ms = int((time.perf_counter() - start) * 1000)
        log_llm_call(model or settings.llm_model, _count_tokens(prompt_text), _count_tokens(content), latency_ms)
        return LLMResponse(
            content=content,
            model=model or settings.llm_model,
            prompt_tokens=_count_tokens(prompt_text),
            completion_tokens=_count_tokens(content),
            latency_ms=latency_ms,
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        content = self._compose(messages)
        for i in range(0, len(content), 4):
            if settings.llm_mock_stream_delay:
                await asyncio.sleep(settings.llm_mock_stream_delay)
            yield StreamEvent(content=content[i : i + 4])
        yield StreamEvent(
            usage={
                "prompt_tokens": _count_tokens("".join(str(m.get("content", "")) for m in messages)),
                "completion_tokens": _count_tokens(content),
            },
            finish_reason="stop",
        )
