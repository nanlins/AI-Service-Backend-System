from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @model_validator(mode="after")
    def _check_reap_lock_invariant(self) -> "Settings":
        # 锁 TTL 必须大于 reap 阈值并留余量：否则锁刚过期任务就被复位重投，
        # 两个 worker 可能对同一任务先后执行 handler（reaper/CAS 边界竞态）。
        if self.task_lock_ttl <= self.task_reap_stale_seconds:
            raise ValueError(
                f"task_lock_ttl({self.task_lock_ttl}) 必须大于 task_reap_stale_seconds"
                f"({self.task_reap_stale_seconds})，请留出余量防止 reaper 竞态"
            )
        return self

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> "Settings":
        if not self.jwt_secret.get_secret_value():
            raise ValueError(
                "JWT_SECRET 环境变量未设置：请设置一个随机字符串（可用 python -c \"import secrets;print(secrets.token_hex(32))\")"
            )
        return self

    @model_validator(mode="after")
    def _check_llm_key_when_openai(self) -> "Settings":
        if self.llm_provider == "openai" and not self.llm_api_key:
            raise ValueError(
                "LLM_PROVIDER=openai 时必须设置 LLM_API_KEY（或 OPENAI_API_KEY）环境变量，"
                "禁止在代码/配置文件里写死密钥"
            )
        return self

    app_name: str = "AI Backend"
    app_env: str = "dev"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://postgres:dev_pg_pw_001@localhost:5435/ai_backend"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    auto_migrate: bool = False

    redis_url: str = "redis://localhost:6381/0"

    rabbitmq_url: str = "amqp://admin:dev_mq_pw_001@localhost:5672/"
    task_exchange: str = "ai_tasks"
    task_queue: str = "ai_tasks.workers"
    task_dead_exchange: str = "ai_tasks.dlx"
    task_dead_queue: str = "ai_tasks.dead"
    task_max_retries: int = 3
    # 必须 > task_reap_stale_seconds（启动时校验）：保证 worker 存活期间锁不先于 reap 过期
    task_lock_ttl: int = 600
    task_status_ttl: int = 3600
    worker_prefetch: int = 5
    task_reap_interval: int = 60
    task_reap_stale_seconds: int = 300
    # 失败重投延迟（指数退避）：delay = min(max, base * 2^(retry-1))，由 worker 内的
    # 延迟队列 pump 定时取出并重投（避免失败立即重投打爆队列/上游）。
    task_retry_base_delay: int = 5
    task_retry_max_delay: int = 60
    task_retry_pump_interval: int = 5

    # JWT：无默认值、启动时校验非空，必须通过环境变量注入（缺失即报错）。
    jwt_secret: SecretStr = Field(default_factory=lambda: SecretStr(""))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    llm_provider: Literal["mock", "openai"] = "mock"
    llm_api_base: str = "https://api.openai.com/v1"
    # 密钥仅从环境变量读取（兼容 LLM_API_KEY / OPENAI_API_KEY，亦允许字段名传入），无默认值。
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY", "llm_api_key"),
    )
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0
    llm_mock_delay: float = 0.0
    llm_mock_stream_delay: float = 0.0

    # 采样参数默认值（可被调用方按请求覆盖）：对话 0.5~0.7；代码/结构化任务传 0~0.2。
    llm_temperature: float = 0.7
    llm_top_p: float = 1.0
    llm_max_tokens: int | None = None
    llm_stop: list[str] = Field(default_factory=list)

    # 上下文工程：token 预算与摘要触发
    chat_history_limit: int = 20
    chat_token_budget: int = 8000
    chat_enable_tools: bool = True
    chat_max_tool_rounds: int = 5
    chat_summary_prompt: str = (
        "请把以下多轮对话压缩成一份简洁的中文摘要（保留关键事实、结论与未决问题），不要编造。"
    )

    # CORS：开发默认仅本机来源，生产通过环境变量覆盖
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )

    # 限流（Redis 滑动窗口）
    rate_limit_auth_attempts: int = 10
    rate_limit_auth_window: int = 60
    rate_limit_message_attempts: int = 60
    rate_limit_message_window: int = 60


settings = Settings()
