from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "internal_error"
    http_status = 500
    default_message = "服务内部错误"

    def __init__(self, message: str | None = None, detail: dict[str, Any] | None = None) -> None:
        self.message = message or self.default_message
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404
    default_message = "资源不存在"


class AuthError(AppError):
    code = "unauthorized"
    http_status = 401
    default_message = "未认证或凭证无效"


class ForbiddenError(AppError):
    code = "forbidden"
    http_status = 403
    default_message = "无权访问该资源"


class ConflictError(AppError):
    code = "conflict"
    http_status = 409
    default_message = "资源冲突"


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422
    default_message = "请求参数校验失败"


class RateLimitError(AppError):
    code = "rate_limited"
    http_status = 429
    default_message = "请求过于频繁，请稍后重试"

    def __init__(self, message: str | None = None, detail: dict[str, Any] | None = None, retry_after: int = 0) -> None:
        self.retry_after = retry_after
        super().__init__(message, detail)


class UpstreamError(AppError):
    code = "upstream_error"
    http_status = 502
    default_message = "上游服务异常"
