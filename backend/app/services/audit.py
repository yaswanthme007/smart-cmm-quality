"""Audit trail writer. Every state change calls `record` inside the same transaction."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core import clock
from app.core.logging import request_id_var
from app.models import AuditLog


@dataclass(frozen=True)
class Actor:
    """Who caused a change. `user_id=None` means the system (worker, ingestion pipeline)."""

    user_id: uuid.UUID | None = None
    role: str | None = "SYSTEM"
    ip: str | None = None


SYSTEM = Actor()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def snapshot(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    """Column values of an ORM object as JSON-safe dict (password hashes always excluded)."""
    skip = {"password_hash"} | (exclude or set())
    mapper = inspect(obj).mapper
    return {
        col.key: to_jsonable(getattr(obj, col.key))
        for col in mapper.column_attrs
        if col.key not in skip
    }


def record(
    session: Session,
    *,
    actor: Actor,
    action: str,
    entity: str,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        at=clock.now(),
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=to_jsonable(before) if before is not None else None,
        after=to_jsonable(after) if after is not None else None,
        request_id=request_id_var.get(),
        ip=actor.ip,
    )
    session.add(entry)
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reduce two snapshots to only the changed keys."""
    keys = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    keys.discard("updated_at")
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}
