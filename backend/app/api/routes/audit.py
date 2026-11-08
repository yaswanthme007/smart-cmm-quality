"""Audit log viewer (Admin, Quality Head). Read-only by design."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AUDIT_READERS, require_roles
from app.core.db import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_user_id: Any = None
    actor_name: str | None = None
    actor_role: str | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None
    ip: str | None


class AuditPage(BaseModel):
    total: int
    items: list[AuditEntryOut]


@router.get("", response_model=AuditPage)
def list_audit(
    entity: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_user_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*AUDIT_READERS)),
) -> AuditPage:
    q = select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.actor_user_id)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
    if date_from:
        q = q.where(AuditLog.at >= date_from)
    if date_to:
        q = q.where(AuditLog.at < date_to)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    items = []
    for entry, name in rows:
        out = AuditEntryOut.model_validate(entry)
        out.actor_name = name
        items.append(out)
    return AuditPage(total=total, items=items)
