"""Live events over Postgres LISTEN/NOTIFY (Section 6 D5).

`publish` runs pg_notify inside the caller's transaction, so listeners only hear about data that
was committed. Payloads carry IDs, not objects (NOTIFY payload limit).

`EventHub` holds one LISTEN connection per API process and fans events out to SSE clients.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

import psycopg
from sqlalchemy import make_url, text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL = "events"


def publish(session: Session, event_type: str, **data: Any) -> None:
    payload = json.dumps({"type": event_type, **data}, default=str)
    session.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})


def _psycopg_dsn() -> str:
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


class EventHub:
    """Fan-out of NOTIFY events to per-client asyncio queues."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def dispatch(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    async def _listen_forever(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    _psycopg_dsn(), autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    logger.info("event hub listening on channel %s", CHANNEL)
                    async for note in conn.notifies():
                        try:
                            self.dispatch(json.loads(note.payload))
                        except json.JSONDecodeError:
                            logger.warning("bad event payload: %s", note.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("event hub connection lost; retrying in 2 s", exc_info=True)
                await asyncio.sleep(2)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen_forever())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


hub = EventHub()
