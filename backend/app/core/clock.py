"""Clock used by the domain services.

Normally `now()` is the real UTC time. Seeding synthetic history runs inside `shifted_to(t)`,
which moves "now" back to `t` while time still flows: any duration measured inside (for example
an alert's generation_ms) is the real processing time, never a typed-in number.
`history_mode()` also tells services not to queue emails for back-dated events.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

_offset: ContextVar[timedelta] = ContextVar("clock_offset", default=timedelta(0))
_history: ContextVar[bool] = ContextVar("clock_history", default=False)


def now() -> datetime:
    return datetime.now(UTC) + _offset.get()


@contextmanager
def shifted_to(moment: datetime) -> Iterator[None]:
    token = _offset.set(moment - datetime.now(UTC))
    try:
        yield
    finally:
        _offset.reset(token)


@contextmanager
def history_mode() -> Iterator[None]:
    token = _history.set(True)
    try:
        yield
    finally:
        _history.reset(token)


def in_history() -> bool:
    return _history.get()
