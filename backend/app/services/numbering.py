"""Human-readable sequential numbers (NC-2026-00042, R-2026-000123), safe under concurrency."""

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import InstrumentedAttribute, Session

_LOCK_IDS = {"NC": 7101, "R": 7102}


def next_number(
    session: Session, column: InstrumentedAttribute[str], prefix: str, when: datetime, width: int
) -> str:
    # Transaction-scoped advisory lock serializes number allocation per prefix.
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_IDS[prefix]})
    stem = f"{prefix}-{when.year}-"
    last = session.scalar(select(func.max(column)).where(column.like(f"{stem}%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{seq:0{width}d}"
