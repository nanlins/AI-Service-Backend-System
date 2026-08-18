from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.errors import AppError, RateLimitError, UpstreamError
from app.llm.base import (
    LLMClient,
    LLMResponse,
    MessageDict,
    SamplingParams,
    StreamEvent,
    ToolCall,
    ToolCallPart,
    clean_usage,
    log_llm_call,
    sampling_overrides,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


def _backoff(retries: int) -> float:
    return 0.5 * (2**retries)


def _classify_error(resp: httpx.Response) -> AppError:
    if resp.status_code == 401:
        return UpstreamError("LLM API 密钥无效或未授权（401）", detail={"status": resp.status_code})
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "1") or 1)
        return RateLimitError("LLM 请求被限流（429）", retry_after=retry_after)
    if resp.status_code >= 500:
        return UpstreamError(f"LLM 服务异常: HTTP {resp.status_code}", detail={"status": resp.status_code})
    return UpstreamError(f"LLM 请求被拒绝: HTTP {resp.status_code}", detail={"body": resp.text[:500]})


class OpenAICompatLLM(LLMClient):
    """OpenAI Chat Completions 兼容客户端（可用于任意兼容供应商）。"""

    def __init__(
        self,
        base_url: str,
        credential: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {credential}"},
            timeout=timeout,
            transport=transport,
        )

    def _payload(
        self,
        messages: list[MessageDict],
        model: str | None,
        sampling: SamplingParams | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
        }
        overrides = sampling_overrides(sampling)
        payload.update({k: v for k, v in overrides.items() if v is not None})
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def complete(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        payload = self._payload(messages, model, sampling, stream=False)
        if tools is not None:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        start = time.perf_counter()
        retries = 0
        while True:
            try:
                resp = await self._client.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                if retries < MAX_RETRIES:
                    retries += 1
                    delay = _backoff(retries)
                    logger.warning("LLM 网络错误，第 %s 次重试（%.1fs）: %s", retries, delay, exc)
                    await asyncio.sleep(delay)
                    continue
                raise UpstreamError(f"LLM 请求失败（网络错误）: {exc}", detail={"retries": retries}) from exc
            if resp.status_code == 429 or resp.status_code >= 500:
                if retries < MAX_RETRIES:
                    retries += 1
                    delay = _backoff(retries)
                    logger.warning("LLM HTTP %s，第 %s 次重试（%.1fs）", resp.status_code, retries, delay)
                    await asyncio.sleep(delay)
                    continue
                raise _classify_error(resp)
            if resp.status_code >= 400:
                raise _classify_error(resp)
            break

        data = resp.json()
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason", "stop")
        message = choice.get("message", {}) or {}
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = [ToolCall(**tc) for tc in raw_tool_calls] if raw_tool_calls else None
        usage = data.get("usage", {})
        latency_ms = int((time.perf_counter() - start) * 1000)
        log_llm_call(
            data.get("model", model or self.model),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            latency_ms,
        )
        return LLMResponse(
            content=message.get("content") or "",
            model=data.get("model", model or self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[MessageDict],
        model: str | None = None,
        sampling: SamplingParams | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        payload = self._payload(messages, model, sampling, stream=True)
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    err = _classify_error(httpx.Response(resp.status_code, text=body.decode(errors="replace")))
                    raise err
                tool_calls_acc: dict[int, ToolCallPart] = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage")
                    if usage:
                        # 清洗 usage：丢弃 *_details 等对象字段，避免 pydantic 校验中断流
                        yield StreamEvent(usage=clean_usage(usage))
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {}) or {}
                    finish = choice.get("finish_reason")
                    content = delta.get("content")
                    if content:
                        yield StreamEvent(content=content)
                    for tc in delta.get("tool_calls") or []:
                        index = tc.get("index", 0)
                        acc = tool_calls_acc.setdefault(index, ToolCallPart(index=index))
                        fn = tc.get("function", {}) or {}
                        if tc.get("id"):
                            acc.id = tc["id"]
                        if fn.get("name"):
                            acc.name = fn["name"]
                        arg = fn.get("arguments") or ""
                        if arg:
                            acc.arguments += arg
                        yield StreamEvent(
                            tool_calls=[
                                ToolCallPart(index=index, id=acc.id, name=acc.name, arguments=arg)
                            ]
                        )
                    if finish:
                        yield StreamEvent(finish_reason=finish)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"LLM 流式请求失败（网络错误）: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()
