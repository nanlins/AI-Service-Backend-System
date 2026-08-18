from app.services.chat_service import (
    DEFAULT_SYSTEM_PROMPT,
    SYSTEM_TRUST_NOTE,
    build_context_messages,
    wrap_untrusted,
)


def test_build_context_default_system_prompt():
    messages = build_context_messages(None, None, [])
    assert len(messages) == 1
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith(DEFAULT_SYSTEM_PROMPT)
    assert SYSTEM_TRUST_NOTE in messages[0]["content"]


def test_build_context_with_summary_and_history_window():
    history = [(("user" if i % 2 == 0 else "assistant"), f"msg{i}") for i in range(10)]
    messages = build_context_messages("自定义角色", "旧对话摘要", history, limit=4)
    assert messages[0]["content"].startswith("自定义角色")
    assert messages[1]["content"].startswith("以下是更早对话的摘要")
    assert len(messages) == 2 + 4
    assert messages[-1] == {"role": "assistant", "content": "msg9"}
    # 用户消息必须被不可信标签包裹（提示注入防护）
    assert messages[-4] == {"role": "user", "content": wrap_untrusted("msg6")}


def test_build_context_history_smaller_than_limit():
    history = [("user", "hi"), ("assistant", "hello")]
    messages = build_context_messages(None, None, history, limit=20)
    assert len(messages) == 3
    assert messages[1]["content"] == wrap_untrusted("hi")
    assert messages[2] == {"role": "assistant", "content": "hello"}


def test_estimate_tokens_cjk():
    from app.services.chat_service import estimate_tokens

    assert estimate_tokens("你好世界") == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 1
