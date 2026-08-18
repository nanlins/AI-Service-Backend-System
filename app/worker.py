import asyncio

from app.core.logging import setup_logging
from app.mq.consumer import run_worker

setup_logging()

if __name__ == "__main__":
    asyncio.run(run_worker())
