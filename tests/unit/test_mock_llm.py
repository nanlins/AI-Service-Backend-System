from app.llm.mock import MockLLM


async def test_mock_complete_returns_content_and_usage():
    llm = MockLLM()
    resp = await llm.complete(
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ]
    )
    assert "你好" in resp.content
    assert resp.prompt_tokens > 0
    assert resp.completion_tokens > 0
    assert resp.latency_ms >= 0
    assert resp.finish_reason == "stop"


async def test_mock_summarize_prompt_produces_summary():
    llm = MockLLM()
    resp = await llm.complete(
        [
            {"role": "system", "content": "请生成摘要"},
            {"role": "user", "content": "很长的文本"},
        ]
    )
    assert resp.content.startswith("摘要：")


async def test_mock_stream_concat_equals_compose():
    llm = MockLLM()
    messages = [{"role": "user", "content": "流式测试"}]
    events = [e async for e in llm.stream(messages)]
    content = "".join(e.content for e in events)
    assert len(content) > 0
    complete = await llm.complete(messages)
    assert content == complete.content
    # 流末事件应携带 usage 与 finish_reason
    last = events[-1]
    assert last.usage and last.usage["completion_tokens"] > 0
    assert last.finish_reason == "stop"
