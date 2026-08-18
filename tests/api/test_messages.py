import pytest

from app.llm.base import LLMClient, set_llm

PREFIX = "/api/v1"


class FailingLLM(LLMClient):
    """总是抛异常的 LLM，用于验证 LLM 失败时的数据完整性。"""

    async def complete(self, messages, model=None, sampling=None):
        raise RuntimeError("boom")

    async def stream(self, messages, model=None, sampling=None):
        raise RuntimeError("boom")
        yield  # pragma: no cover - 使函数成为生成器


@pytest.fixture
def failing_llm():
    set_llm(FailingLLM())
    yield
    set_llm(None)


async def _new_session(client, headers) -> int:
    resp = await client.post(f"{PREFIX}/sessions", json={"title": "chat"}, headers=headers)
    return resp.json()["id"]


async def test_send_message_returns_reply_and_persists(client, auth_headers):
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "你好，介绍一下你自己"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    assert "你好" in body["assistant_message"]["content"]
    assert body["assistant_message"]["model"] is not None

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)
    messages = resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]


async def test_multi_turn_history_order(client, auth_headers):
    session_id = await _new_session(client, auth_headers)
    for text in ["第一条", "第二条"]:
        resp = await client.post(
            f"{PREFIX}/sessions/{session_id}/messages",
            json={"content": text},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)
    messages = resp.json()
    assert len(messages) == 4
    assert messages[0]["content"] == "第一条"
    assert messages[2]["content"] == "第二条"

    resp = await client.get(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)
    assert resp.json()["message_count"] == 4


async def test_stream_reply_sse(client, auth_headers):
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "流式测试", "stream": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    assert "data: " in text
    assert "data: [DONE]" in text
    assert '"delta"' in text

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)
    assert len(resp.json()) == 2  # 流式结束后消息已落库


async def test_empty_content_rejected(client, auth_headers):
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages", json={"content": ""}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_stream_error_keeps_user_message_single_response(client, auth_headers, failing_llm):
    """LLM 流式失败：只发 error 事件 + [DONE]，不抛异常造成双重响应；用户消息必须保留。"""
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "触发失败", "stream": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert '"error": "upstream_error"' in resp.text
    assert "data: [DONE]" in resp.text
    assert '"delta"' not in resp.text

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)
    messages = resp.json()
    assert len(messages) == 1, "LLM 失败后用户消息应保留"
    assert messages[0]["role"] == "user"

    resp = await client.get(f"{PREFIX}/sessions/{session_id}", headers=auth_headers)
    assert resp.json()["message_count"] == 1


async def test_reply_llm_failure_returns_502_and_keeps_user_message(client, auth_headers, failing_llm):
    """非流式 LLM 失败：返回 502（统一错误格式），且用户消息不丢失。"""
    session_id = await _new_session(client, auth_headers)
    resp = await client.post(
        f"{PREFIX}/sessions/{session_id}/messages",
        json={"content": "触发失败"},
        headers=auth_headers,
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"

    resp = await client.get(f"{PREFIX}/sessions/{session_id}/messages", headers=auth_headers)
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
