"""Alerts: my alerts list, mark read (Section 14)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Alert, NonConformance, User
from app.models.enums import AlertKind, Role

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AlertKind
    nc_id: uuid.UUID | None
    nc_no: str | None = None
    spc_signal_id: uuid.UUID | None
    level: int
    recipient_user_id: uuid.UUID | None
    recipient_name: str | None = None
    title: str
    body: str
    source_received_at: datetime | None
    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None
    generation_ms: int | None


class AlertPage(BaseModel):
    total: int
    unread: int
    items: list[AlertOut]


@router.get("", response_model=AlertPage)
def list_alerts(
    mine: bool = True,
    kind: AlertKind | None = None,
    unread_only: bool = False,
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertPage:
    q = (
        select(Alert, NonConformance.nc_no, User.full_name)
        .outerjoin(NonConformance, NonConformance.id == Alert.nc_id)
        .outerjoin(User, User.id == Alert.recipient_user_id)
    )
    # Plant-wide alert list is for Quality Head / Admin / Viewer; others always see their own.
    if mine or user.role not in (Role.QUALITY_HEAD, Role.ADMIN, Role.VIEWER):
        q = q.where(Alert.recipient_user_id == user.id)
    if kind:
        q = q.where(Alert.kind == kind)
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.recipient_user_id == user.id, Alert.read_at.is_(None))
        )
        or 0
    )
    if unread_only:
        q = q.where(Alert.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(Alert.created_at.desc()).limit(limit).offset(offset)).all()
    items = []
    for alert, nc_no, name in rows:
        out = AlertOut.model_validate(alert)
        out.nc_no, out.recipient_name = nc_no, name
        items.append(out)
    return AlertPage(total=total, unread=unread, items=items)


@router.post("/{alert_id}/read", response_model=AlertOut)
def mark_read(
    alert_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None or alert.recipient_user_id != user.id:
        raise HTTPException(404, "alert not found")
    if alert.read_at is None:
        alert.read_at = datetime.now(UTC)
        db.commit()
    return alert


@router.post("/read-all", status_code=204)
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    now = datetime.now(UTC)
    for alert in db.scalars(
        select(Alert).where(Alert.recipient_user_id == user.id, Alert.read_at.is_(None))
    ):
        alert.read_at = now
    db.commit()
