"""死信队列人工恢复入口：python scripts/requeue_dead.py [--requeue-all]

默认仅统计 ai_tasks.dead 积压并预览前几条；加 --requeue-all 才把死信消息重新投递
回主交换机（由 worker 重新消费）。适合排查"重试耗尽/被拒绝/过期"的任务。

可选环境变量：
  RABBITMQ_URL=amqp://admin:dev_mq_pw_001@localhost:5672/
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aio_pika  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.mq.topology import declare_topology  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(requeue_all: bool) -> int:
    url = os.environ.get("RABBITMQ_URL", settings.rabbitmq_url)
    connection = await aio_pika.connect_robust(url)
    try:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        await declare_topology(channel)
        queue = await channel.get_queue(settings.task_dead_queue)
        # 预览积压量
        declared = await channel.get_queue(settings.task_dead_queue)
        stats = await declared.declare()
        logger.info("死信队列 %s 积压消息数: %s", settings.task_dead_queue, stats.message_count)

        if not requeue_all:
            logger.info("预览模式：请加 --requeue-all 执行重投")
            return 0

        exchange = await channel.declare_exchange(
            settings.task_exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )
        processed = 0
        async with queue.iterator() as it:
            async for message in it:
                body = json.loads(message.body)
                task_id = body.get("task_id")
                task_type = body.get("task_type", "recover")
                logger.info("重投死信 task %s (type=%s)", task_id, task_type)
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps({"task_id": task_id}).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        content_type="application/json",
                    ),
                    routing_key=f"task.{task_type}",
                )
                await message.ack()
                processed += 1
        logger.info("共重投 %d 条死信消息", processed)
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="死信队列恢复入口")
    parser.add_argument("--requeue-all", action="store_true", help="把全部死信重投回主队列")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.requeue_all)))
