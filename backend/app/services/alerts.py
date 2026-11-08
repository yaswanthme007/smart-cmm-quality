"""In-app alerts (+ email via outbox) with measured generation time (Section 10.5)."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import clock, events
from app.models import Alert, User
from app.models.enums import AlertKind
from app.services.notifications.outbox import enqueue_email


def create_alert(
    session: Session,
    *,
    kind: AlertKind,
    recipient_user_id: uuid.UUID | None,
    title: str,
    body: str,
    nc_id: uuid.UUID | None = None,
    spc_signal_id: uuid.UUID | None = None,
    level: int = 0,
    source_received_at: datetime | None = None,
    email: bool = True,
) -> Alert:
    """Insert the alert row, queue its email, and NOTIFY on commit.

    generation_ms = created_at - source_received_at (K3). created_at is set explicitly to the
    moment the row is built inside the ingest transaction, which commits right after.
    """
    created_at = clock.now()
    generation_ms = None
    if source_received_at is not None:
        generation_ms = max(0, int((created_at - source_received_at).total_seconds() * 1000))
    alert = Alert(
        kind=kind,
        nc_id=nc_id,
        spc_signal_id=spc_signal_id,
        level=level,
        recipient_user_id=recipient_user_id,
        title=title[:255],
        body=body,
        source_received_at=source_received_at,
        generation_ms=generation_ms,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(alert)
    session.flush()

    recipient = session.get(User, recipient_user_id) if recipient_user_id else None
    if email and recipient is not None and not clock.in_history():
        enqueue_email(session, to=recipient.email, subject=title, body=body, alert_id=alert.id)
    events.publish(
        session,
        "alert.created",
        id=alert.id,
        kind=kind.value,
        recipient_user_id=recipient_user_id,
        nc_id=nc_id,
        title=alert.title,
    )
    return alert
