from collections.abc import AsyncGenerator

from app.core.config import settings
from app.llm.base import (
    LLMClient,
    LLMResponse,
    StreamEvent,
    ToolCallPart,
    set_llm,
)

PREFIX = "/api/v1"


class ToolCallLLM(LLMClient):
    """流式返回工具调用事件的 LLM。"""

    async def complete(self, messages, model=None, sampling=None):
        return LLMResponse(content="", model="tool-model", prompt_tokens=0, completion_tokens=0)

    async def stream(self, messages, model=None, sampling=None) -> AsyncGenerator[StreamEvent, None]:
        yield StreamEvent(tool_calls=[ToolCallPart(index=0, id="call_1", name="get_weather", arguments="")])
        yield StreamEvent(tool_calls=[ToolCallPart(index=0, arguments='{"city":"北京"}')])
        yield StreamEvent(finish_reason="tool_calls")
        yield StreamEvent(usage={"prompt_tokens": 5, "completion_tokens": 3})


async def _new_session(client, headers) -> int:
    resp = await client.post(f"{PREFIX}/sessions", json={"title": "chat"}, headers=headers)
    return resp.json()["id"]


async def test_stream_tool_calls_persisted(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.llm.base.set_llm", lambda c: set_llm(c))
    set_llm(ToolCallLLM())
    try:
        session_id = await _new_session(client, auth_headers)
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": "北京天气", "stream": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "data: [DONE]" in resp.text

        msgs = (await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)).json()
        assistant = msgs[-1]
        assert assistant["role"] == "assistant"
        assert assistant["tool_calls"] == [
            {"index": 0, "id": "call_1", "name": "get_weather", "arguments": '{"city":"北京"}'}
        ]
        assert assistant["tool_call_id"] == "call_1"
        assert assistant["finish_reason"] == "tool_calls"
    finally:
        set_llm(None)


async def test_sampling_override_sent_to_llm(client, auth_headers, monkeypatch):
    captured: dict = {}

    class CaptureLLM(LLMClient):
        async def complete(self, messages, model=None, sampling=None, tools=None, tool_choice=None):
            captured["sampling"] = sampling
            return LLMResponse(content="x", model="m", prompt_tokens=0, completion_tokens=0)

        async def stream(self, messages, model=None, sampling=None):
            yield StreamEvent(content="x")

    set_llm(CaptureLLM())
    try:
        session_id = await _new_session(client, auth_headers)
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": "hi", "temperature": 0.2, "max_tokens": 50},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert captured["sampling"].temperature == 0.2
        assert captured["sampling"].max_tokens == 50
    finally:
        set_llm(None)


async def test_summarization_writes_session_summary(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "chat_history_limit", 3)
    try:
        session_id = await _new_session(client, auth_headers)
        for i in range(4):  # 4 条历史 > limit=3，触发摘要
            resp = await client.post(
                f"{PREFIX}/sessions/{session_id}/messages",
                json={"content": f"第{i}条消息"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
        session = (await client.get(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)).json()
        assert session["summary"] is not None
        assert "摘要" in session["summary"]
    finally:
        monkeypatch.undo()


async def test_reply_truncation_sets_finish_reason(client, auth_headers, monkeypatch):
    from app.llm.mock import MockLLM

    class TruncatingMock(MockLLM):
        async def complete(self, messages, model=None, sampling=None, tools=None, tool_choice=None):
            resp = await super().complete(messages, model, sampling, tools, tool_choice)
            return resp.model_copy(update={"finish_reason": "length"})

    set_llm(TruncatingMock())
    try:
        session_id = await _new_session(client, auth_headers)
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": "触发截断"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["assistant_message"]["finish_reason"] == "length"
    finally:
        set_llm(None)


class TailErrorLLM(LLMClient):
    """已产出完整内容 + finish_reason 后，在收尾阶段（如 usage 解析）抛异常的 LLM。"""

    async def complete(self, messages, model=None, sampling=None):
        return LLMResponse(content="", model="m", prompt_tokens=0, completion_tokens=0)

    async def stream(self, messages, model=None, sampling=None):
        yield StreamEvent(content="完整回答")
        yield StreamEvent(finish_reason="stop")
        # 模拟 usage 终包含 *_details 对象导致 pydantic 校验抛错（修复前会中断并丢内容）
        raise RuntimeError("usage parse boom")


async def test_stream_tail_error_degrades_to_save_full_answer(client, auth_headers):
    """收尾阶段异常但内容已完整：应降级保存完整回答并返回 done，而非丢内容。"""
    set_llm(TailErrorLLM())
    try:
        session_id = await _new_session(client, auth_headers)
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": "你好", "stream": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        text = resp.text
        assert '"delta"' in text and "完整回答" in text
        assert '"done": true' in text or '"done":true' in text
        assert "data: [DONE]" in text
        assert "upstream_error" not in text

        msgs = (await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)).json()
        assistant = msgs[-1]
        assert assistant["role"] == "assistant"
        assert assistant["content"] == "完整回答"
        assert assistant["finish_reason"] == "stop"
    finally:
        set_llm(None)


async def test_tool_call_loop_weather(client, auth_headers):
    """MockLLM 命中「天气」触发 get_weather 工具：完整工具调用链路落库并返回最终回答。"""
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "北京天气怎么样？"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    final = resp.json()["assistant_message"]
    assert "25" in final["content"]  # 最终回答引用了工具结果

    msgs = (await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)).json()
    roles = [m["role"] for m in msgs]
    # 链路：user -> assistant(tool_calls) -> tool -> assistant(最终回答)
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_call_msg = msgs[1]
    assert tool_call_msg["tool_calls"][0]["function"]["name"] == "get_weather"
    tool_result = msgs[2]
    assert tool_result["tool_call_id"] == tool_call_msg["tool_calls"][0]["id"]
    assert "北京" in tool_result["content"]


async def test_tool_call_loop_calculate(client, auth_headers):
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "帮我计算 3+4*5"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    final = resp.json()["assistant_message"]
    assert "23" in final["content"]

    msgs = (await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)).json()
    tool_result = [m for m in msgs if m["role"] == "tool"][0]
    assert '"result": 23' in tool_result["content"]
