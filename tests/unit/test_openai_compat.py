from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import MockTransport

from app.core.errors import RateLimitError, UpstreamError
from app.llm.base import SamplingParams, clean_usage
from app.llm.openai_compat import OpenAICompatLLM

BASE = "https://api.test.com"


def make_llm(handler) -> OpenAICompatLLM:
    return OpenAICompatLLM(
        base_url=BASE,
        credential="sk-test",
        model="test-model",
        transport=MockTransport(handler),
    )


def json_handler(data, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=data)

    return handler


def test_complete_success_with_usage_and_finish_reason():
    llm = make_llm(
        json_handler(
            {
                "model": "test-model",
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
        )
    )

    result = asyncio.run(
        llm.complete([{"role": "user", "content": "hello"}])
    )
    assert result.content == "hi"
    assert result.prompt_tokens == 5
    assert result.completion_tokens == 3
    assert result.finish_reason == "stop"
    assert not result.truncated


def test_complete_truncated_flag_when_length():
    llm = make_llm(
        json_handler(
            {
                "model": "test-model",
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
        )
    )

    result = asyncio.run(llm.complete([{"role": "user", "content": "hello"}]))
    assert result.finish_reason == "length"
    assert result.truncated


async def test_complete_sends_sampling_params():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content.decode()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}], "usage": {}})

    llm = make_llm(handler)
    await llm.complete(
        [{"role": "user", "content": "hello"}],
        sampling=SamplingParams(temperature=0.1, top_p=0.9, max_tokens=100, stop=["END"]),
    )
    assert seen["temperature"] == 0.1
    assert seen["top_p"] == 0.9
    assert seen["max_tokens"] == 100
    assert seen["stop"] == ["END"]


async def test_complete_429_retries_then_success(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("app.llm.openai_compat._backoff", lambda r: 0)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, text="rate limited")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    llm = make_llm(handler)
    resp = await llm.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert calls["n"] == 3


async def test_complete_500_exhausts_retries(monkeypatch):
    monkeypatch.setattr("app.llm.openai_compat._backoff", lambda r: 0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    llm = make_llm(handler)
    with pytest.raises(UpstreamError):
        await llm.complete([{"role": "user", "content": "hi"}])


async def test_complete_401_raises_auth_error():
    llm = make_llm(json_handler({"error": "invalid key"}, status=401))
    with pytest.raises(UpstreamError, match="401"):
        await llm.complete([{"role": "user", "content": "hi"}])


async def test_complete_429_exhausts_retries_raises_rate_limit(monkeypatch):
    monkeypatch.setattr("app.llm.openai_compat._backoff", lambda r: 0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"}, text="rl")

    llm = make_llm(handler)
    with pytest.raises(RateLimitError):
        await llm.complete([{"role": "user", "content": "hi"}])


async def test_complete_network_error_retries_then_upstream(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr("app.llm.openai_compat._backoff", lambda r: 0)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("conn refused")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    llm = make_llm(handler)
    resp = await llm.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert calls["n"] == 3


async def test_stream_content_usage_finish_reason():
    sse = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: {"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )
    llm = make_llm(lambda request: httpx.Response(200, content=sse.encode()))
    events = [e async for e in llm.stream([{"role": "user", "content": "hi"}])]
    content = "".join(e.content for e in events)
    assert content == "你好"
    assert events[-1].usage == {"prompt_tokens": 3, "completion_tokens": 2}
    assert any(e.finish_reason == "stop" for e in events)


async def test_stream_tool_calls_aggregated():
    sse = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"get_weather","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"city\\":\\"北京\\"}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    llm = make_llm(lambda request: httpx.Response(200, content=sse.encode()))
    events = [e async for e in llm.stream([{"role": "user", "content": "天气"}])]
    parts = [p for e in events for p in e.tool_calls]
    assert len(parts) == 2
    assert parts[0].id == "call_1"
    assert parts[0].name == "get_weather"
    assert "".join(p.arguments for p in parts) == '{"city":"北京"}'
    assert any(e.finish_reason == "tool_calls" for e in events)


async def test_stream_http_error_classified():
    llm = make_llm(lambda request: httpx.Response(401, text="nope"))
    with pytest.raises(UpstreamError, match="401"):
        async for _ in llm.stream([{"role": "user", "content": "hi"}]):
            pass


def test_clean_usage_keeps_only_int_fields():
    raw = {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    }
    assert clean_usage(raw) == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


async def test_stream_usage_with_details_fields_does_not_break():
    """真实上游 usage 终包含 *_details 对象字段：应清洗后正常产流，不中断。"""
    sse = (
        'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: {"usage":{"prompt_tokens":3,"completion_tokens":2,'
        '"prompt_tokens_details":{"cached_tokens":0},'
        '"completion_tokens_details":{"reasoning_tokens":0}}}\n\n'
        "data: [DONE]\n\n"
    )
    llm = make_llm(lambda request: httpx.Response(200, content=sse.encode()))
    events = [e async for e in llm.stream([{"role": "user", "content": "hi"}])]
    content = "".join(e.content for e in events)
    assert content == "你好"
    usage = next(e.usage for e in events if e.usage)
    assert usage == {"prompt_tokens": 3, "completion_tokens": 2}
    assert "prompt_tokens_details" not in usage
    assert any(e.finish_reason == "stop" for e in events)
