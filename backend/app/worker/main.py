"""Worker process (Section 5.2, D6): async loops in one process, no broker.

- outbox dispatcher: sends queued alert emails (every 2 s)
- escalation sweeper: escalates unacknowledged NCs (every 10 s)
- heartbeat: writes settings.worker_heartbeat (every 10 s) for /api/health
- folder watcher: ingests files dropped into data/inbox/<CMM>/ (Section 8.4)

Every job uses FOR UPDATE SKIP LOCKED, so more worker replicas are safe.
"""

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.models import Setting
from app.services import escalation
from app.services.notifications.outbox import dispatch_batch

logger = logging.getLogger("app.worker")

OUTBOX_INTERVAL_S = 2.0
SWEEP_INTERVAL_S = 10.0
HEARTBEAT_INTERVAL_S = 10.0


def run_in_session(job: Callable[[Session], int | None]) -> int | None:
    with get_sessionmaker()() as session:
        try:
            result = job(session)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise


def write_heartbeat(session: Session) -> None:
    now = datetime.now(UTC).isoformat()
    row = session.get(Setting, "worker_heartbeat")
    if row is None:
        session.add(Setting(key="worker_heartbeat", value={"at": now}))
    else:
        row.value = {"at": now}


async def loop(name: str, interval: float, job: Callable[[Session], int | None]) -> None:
    while True:
        try:
            done = await asyncio.to_thread(run_in_session, job)
            if done:
                logger.info("%s: %s", name, done)
        except Exception:
            logger.exception("%s failed", name)
        await asyncio.sleep(interval)


async def main() -> None:
    configure_logging(get_settings().log_level)
    from app.worker.folder_watcher import FolderWatcher

    watcher = FolderWatcher(get_settings().data_dir)
    tasks = [
        asyncio.create_task(loop("outbox", OUTBOX_INTERVAL_S, dispatch_batch)),
        asyncio.create_task(loop("escalation", SWEEP_INTERVAL_S, escalation.sweep)),
        asyncio.create_task(loop("heartbeat", HEARTBEAT_INTERVAL_S, write_heartbeat)),
        asyncio.create_task(watcher.run()),
    ]
    stop = asyncio.Event()
    loop_ = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop_.add_signal_handler(sig, stop.set)
    logger.info("worker started")
    await stop.wait()
    for task in tasks:
        task.cancel()
    watcher.stop()
    logger.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
