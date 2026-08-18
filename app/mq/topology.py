from __future__ import annotations

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel

from app.core.config import settings


async def declare_topology(channel: AbstractChannel) -> None:
    """声明任务拓扑：主交换机/队列 + 死信交换机/队列（幂等）。"""
    await channel.declare_exchange(settings.task_dead_exchange, ExchangeType.FANOUT, durable=True)
    dead_queue = await channel.declare_queue(settings.task_dead_queue, durable=True)
    await dead_queue.bind(settings.task_dead_exchange)

    await channel.declare_exchange(settings.task_exchange, ExchangeType.TOPIC, durable=True)
    queue = await channel.declare_queue(
        settings.task_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.task_dead_exchange,
        },
    )
    await queue.bind(settings.task_exchange, routing_key="task.*")
