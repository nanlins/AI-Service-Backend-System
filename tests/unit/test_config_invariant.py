"""配置不变量与安全默认值校验。"""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def _settings(**kwargs) -> Settings:
    defaults = {"jwt_secret": SecretStr("test-secret-0123456789abcdef0123456789abcdef")}
    defaults.update(kwargs)
    return Settings(_env_file=None, **defaults)


def test_default_lock_ttl_exceeds_reap_threshold():
    s = _settings()
    assert s.task_lock_ttl > s.task_reap_stale_seconds


def test_lock_ttl_equal_to_reap_threshold_rejected():
    with pytest.raises(ValidationError):
        _settings(task_lock_ttl=300, task_reap_stale_seconds=300)


def test_lock_ttl_below_reap_threshold_rejected():
    with pytest.raises(ValidationError):
        _settings(task_lock_ttl=100, task_reap_stale_seconds=300)


def test_jwt_secret_missing_rejected(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, task_lock_ttl=600, task_reap_stale_seconds=300)


def test_openai_provider_without_key_rejected():
    with pytest.raises(ValidationError, match="LLM_API_KEY"):
        _settings(llm_provider="openai", llm_api_key="")


def test_openai_provider_with_key_ok():
    s = _settings(llm_provider="openai", llm_api_key="sk-test")
    assert s.llm_api_key == "sk-test"


def test_mock_provider_does_not_require_key():
    s = _settings(llm_provider="mock")
    assert s.llm_api_key == ""


def test_default_cors_is_localhost_only():
    s = _settings()
    assert "http://localhost:8000" in s.cors_origins
    assert "*" not in s.cors_origins
