from __future__ import annotations

import json
import logging

import aio_pika
from aio_pika.abc import AbstractConnection

from app.core.config import settings
from app.mq.topology import declare_topology

logger = logging.getLogger(__name__)


class TaskPublisher:
    """负责任务消息发布；连接失败时 publish 抛出异常由上层降级处理。"""

    def __init__(self, url: str | None = None) -> None:
        self._url = url or settings.rabbitmq_url
        self._connection: AbstractConnection | None = None

    @property
    def is_ready(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def connect(self) -> None:
        if self.is_ready:
            return
        self._connection = await aio_pika.connect_robust(self._url)
        async with self._connection.channel() as channel:
            await declare_topology(channel)
        logger.info("rabbitmq publisher connected")

    async def publish_task(self, task_id: int, task_type: str) -> None:
        if not self.is_ready:
            await self.connect()
        assert self._connection is not None
        async with self._connection.channel() as channel:
            exchange = await channel.declare_exchange(
                settings.task_exchange, aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps({"task_id": task_id}).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=f"task.{task_type}",
            )
        logger.info("task %s published (type=%s)", task_id, task_type)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None


class PublisherHolder:
    def __init__(self) -> None:
        self.publisher: TaskPublisher = TaskPublisher()

    async def connect(self) -> None:
        try:
            await self.publisher.connect()
        except Exception:
            logger.exception("rabbitmq 连接失败，任务创建将不可用（其他接口不受影响）")

    async def close(self) -> None:
        await self.publisher.close()


publisher_holder = PublisherHolder()
