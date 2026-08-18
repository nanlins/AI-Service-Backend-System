from __future__ import annotations

import logging
from contextvars import ContextVar

# 请求级 request_id：中间件写入，日志过滤器读取，贯穿整个请求链路（含 LLM 调用日志）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [rid=%(request_id)s] %(message)s"


class RequestIdFilter(logging.Filter):
    """把 request_id 注入每条日志记录，供格式化输出。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 过滤器必须挂在 handler 上：Logger.handle 只对本 logger 的 filters 生效，
    # 子 logger 的 record 传播到 root 时不会触发 root 的 filter。
    handler = next(
        (h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)),
        None,
    )
    if handler is None:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
        handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
