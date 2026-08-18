import pytest

from app.core.errors import (
    AppError,
    AuthError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
    ValidationError,
)


@pytest.mark.parametrize(
    ("exc_cls", "code", "status"),
    [
        (AppError, "internal_error", 500),
        (NotFoundError, "not_found", 404),
        (AuthError, "unauthorized", 401),
        (ConflictError, "conflict", 409),
        (ValidationError, "validation_error", 422),
        (RateLimitError, "rate_limited", 429),
        (UpstreamError, "upstream_error", 502),
    ],
)
def test_error_mapping(exc_cls, code, status):
    err = exc_cls()
    assert err.code == code
    assert err.http_status == status
    assert err.message == err.default_message


def test_error_to_dict_with_detail():
    err = NotFoundError("任务不存在", detail={"task_id": 1})
    assert err.to_dict() == {
        "code": "not_found",
        "message": "任务不存在",
        "detail": {"task_id": 1},
    }
