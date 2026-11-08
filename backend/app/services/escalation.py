"""Escalation (Section 10.4). Unacknowledged NCs go to the supervisor (level 1), then the
Quality Head (level 2). Acknowledgement stops escalation; it does not close the NC.

The worker calls `sweep` every 10 s; rows are locked with FOR UPDATE SKIP LOCKED so several
workers never escalate the same NC twice.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, events
from app.models import NonConformance, Part
from app.models.enums import AlertKind, NcStatus
from app.services import audit, settings
from app.services.alerts import create_alert
from app.services.notifications.templates import nc_link
from app.services.ownership import quality_head_id

logger = logging.getLogger(__name__)

UNACKNOWLEDGED = (NcStatus.OPEN,)


def escalate(session: Session, nc: NonConformance, level: int, reason: str) -> bool:
    """Raise `nc` to `level` (1 = supervisor, 2 = Quality Head). Returns True if it escalated."""
    if nc.escalation_level >= level:
        return False
    if level == 1:
        recipient = nc.supervisor_user_id or quality_head_id(session)
        who = "Shift Supervisor"
    else:
        recipient = quality_head_id(session)
        who = "Quality Head"
    before = nc.escalation_level
    nc.escalation_level = level
    part = session.get(Part, nc.part_id) if nc.part_id else None
    title = f"[ESCALATION L{level}] {nc.nc_no} {part.part_no if part else ''} not acknowledged"
    body = "\n".join(
        [
            title,
            f"Escalated to {who}: {reason}.",
            f"Open the NC: {nc_link(nc.id)}",
            "Demo data: synthetic prototype.",
        ]
    )
    create_alert(
        session,
        kind=AlertKind.ESCALATION,
        recipient_user_id=recipient,
        title=title,
        body=body,
        nc_id=nc.id,
        level=level,
    )
    audit.record(
        session,
        actor=audit.SYSTEM,
        action="nc.escalate",
        entity="nonconformance",
        entity_id=nc.id,
        before={"escalation_level": before},
        after={"escalation_level": level, "reason": reason},
    )
    events.publish(session, "nc.updated", id=nc.id)
    return True


def sweep(session: Session, now: datetime | None = None) -> int:
    """Escalate overdue unacknowledged NCs. Returns the number of escalations. Caller commits."""
    now = now or clock.now()
    ncs = session.scalars(
        select(NonConformance)
        .where(NonConformance.status.in_(UNACKNOWLEDGED), NonConformance.escalation_level < 2)
        .order_by(NonConformance.detected_at)
        .with_for_update(skip_locked=True)
    ).all()
    count = 0
    for nc in ncs:
        l1, l2 = settings.escalation_timers(session, nc.severity)
        age = now - nc.detected_at
        if age >= timedelta(seconds=l2) and nc.escalation_level < 2:
            if nc.escalation_level < 1:
                count += escalate(session, nc, 1, f"no acknowledgement after {l1} s")
            count += escalate(session, nc, 2, f"no acknowledgement after {l2} s")
        elif age >= timedelta(seconds=l1) and nc.escalation_level < 1:
            count += escalate(session, nc, 1, f"no acknowledgement after {l1} s")
    if count:
        events.publish(session, "kpi.invalidated")
    return count
