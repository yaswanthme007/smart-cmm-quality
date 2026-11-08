"""Corrective-action workflow and NC state machine (Sections 7.3, 11).

OPEN -> ACKNOWLEDGED -> IN_PROGRESS -> PENDING_VERIFICATION -> CLOSED
                                     ^-- rejected (reason) --'
OPEN / ACKNOWLEDGED -> CANCELLED (Quality Head, reason)

Every transition writes an audit entry (which also feeds the NC timeline) and an nc.updated event.
Permission rules (Section 14.1): the owner works their own NCs, the supervisor NCs in their area,
the Quality Head all NCs; only the Quality Head verifies, rejects or cancels.
"""

import hashlib
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock, events
from app.core.config import get_settings
from app.models import Alert, Evidence, NonConformance, User
from app.models.enums import NcStatus, Role, RootCauseCategory
from app.services import audit
from app.services.ingestion.pipeline import safe_filename

MAX_EVIDENCE_BYTES = 10 * 1024 * 1024
EVIDENCE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
EDITABLE = (NcStatus.ACKNOWLEDGED, NcStatus.IN_PROGRESS)
CANCELLABLE = (NcStatus.OPEN, NcStatus.ACKNOWLEDGED)


class WorkflowError(Exception):
    """Invalid transition or missing data (HTTP 409/422)."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PermissionDenied(Exception):
    pass


def can_work(user: User, nc: NonConformance) -> bool:
    if user.role == Role.QUALITY_HEAD:
        return True
    if user.role == Role.PROCESS_OWNER:
        return nc.owner_user_id == user.id
    if user.role == Role.SUPERVISOR:
        return nc.supervisor_user_id == user.id
    return False


def _require_worker(user: User, nc: NonConformance) -> None:
    if not can_work(user, nc):
        raise PermissionDenied(
            "only the owner, their supervisor or the Quality Head can work this NC"
        )


def _require_quality_head(user: User) -> None:
    if user.role != Role.QUALITY_HEAD:
        raise PermissionDenied("only the Quality Head can do this")


def _transition(
    session: Session,
    nc: NonConformance,
    actor: audit.Actor,
    action: str,
    new_status: NcStatus | None,
    extra_after: dict[str, Any] | None = None,
) -> None:
    before = {"status": nc.status.value}
    if new_status is not None:
        nc.status = new_status
    audit.record(
        session,
        actor=actor,
        action=action,
        entity="nonconformance",
        entity_id=nc.id,
        before=before,
        after={"status": nc.status.value} | (extra_after or {}),
    )
    events.publish(session, "nc.updated", id=nc.id, status=nc.status.value)
    events.publish(session, "kpi.invalidated")


def acknowledge(session: Session, nc: NonConformance, user: User, actor: audit.Actor) -> None:
    _require_worker(user, nc)
    if nc.status != NcStatus.OPEN:
        raise WorkflowError(f"cannot acknowledge an NC in status {nc.status.value}")
    now = clock.now()
    nc.acknowledged_at = now
    nc.acknowledged_by = user.id
    for alert in session.scalars(
        select(Alert).where(Alert.nc_id == nc.id, Alert.acknowledged_at.is_(None))
    ):
        alert.acknowledged_at = now
    _transition(session, nc, actor, "nc.acknowledge", NcStatus.ACKNOWLEDGED)


UPDATABLE_FIELDS = (
    "containment",
    "root_cause_category",
    "root_cause",
    "corrective_action",
    "preventive_action",
    "target_date",
)


def update_actions(
    session: Session, nc: NonConformance, user: User, actor: audit.Actor, changes: dict[str, Any]
) -> None:
    _require_worker(user, nc)
    if nc.status == NcStatus.OPEN:
        raise WorkflowError("acknowledge the NC before recording actions")
    if nc.status not in EDITABLE:
        raise WorkflowError(f"cannot edit an NC in status {nc.status.value}")
    before = {k: audit.to_jsonable(getattr(nc, k)) for k in changes}
    for key, value in changes.items():
        if key not in UPDATABLE_FIELDS:
            raise WorkflowError(f"field {key} cannot be changed here", 422)
        if key == "root_cause_category" and value is not None:
            value = RootCauseCategory(value)
        setattr(nc, key, value)
    audit.record(
        session,
        actor=actor,
        action="nc.update",
        entity="nonconformance",
        entity_id=nc.id,
        before=before,
        after={k: audit.to_jsonable(getattr(nc, k)) for k in changes},
    )
    if nc.status == NcStatus.ACKNOWLEDGED and (nc.containment or nc.root_cause):
        _transition(session, nc, actor, "nc.start", NcStatus.IN_PROGRESS)
    else:
        events.publish(session, "nc.updated", id=nc.id, status=nc.status.value)


def add_evidence(
    session: Session,
    nc: NonConformance,
    user: User,
    actor: audit.Actor,
    filename: str,
    data: bytes,
    note: str | None,
) -> Evidence:
    _require_worker(user, nc)
    if nc.status not in EDITABLE:
        raise WorkflowError(f"cannot add evidence to an NC in status {nc.status.value}")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise WorkflowError("evidence file is larger than 10 MB", 413)
    if not data:
        raise WorkflowError("evidence file is empty", 422)
    ext = Path(filename).suffix.lower()
    if ext not in EVIDENCE_TYPES:
        raise WorkflowError(
            f"evidence type not allowed; use {', '.join(sorted(EVIDENCE_TYPES))}", 415
        )
    rel = Path("evidence") / str(nc.id) / f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    path = get_settings().data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    ev = Evidence(
        nc_id=nc.id,
        filename=safe_filename(filename),
        storage_path=str(rel),
        mime=EVIDENCE_TYPES[ext],
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        note=note,
        uploaded_by=user.id,
    )
    session.add(ev)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="nc.evidence",
        entity="nonconformance",
        entity_id=nc.id,
        after={"evidence_id": ev.id, "filename": ev.filename, "size": ev.size, "note": note},
    )
    if nc.status == NcStatus.ACKNOWLEDGED:
        _transition(session, nc, actor, "nc.start", NcStatus.IN_PROGRESS)
    else:
        events.publish(session, "nc.updated", id=nc.id)
    return ev


def submit(session: Session, nc: NonConformance, user: User, actor: audit.Actor) -> None:
    _require_worker(user, nc)
    if nc.status != NcStatus.IN_PROGRESS:
        raise WorkflowError(f"cannot submit an NC in status {nc.status.value}")
    missing = [
        label
        for label, ok in [
            ("containment", nc.containment),
            ("root cause category", nc.root_cause_category),
            ("root cause", nc.root_cause),
            ("corrective action", nc.corrective_action),
            ("target date", nc.target_date),
        ]
        if not ok
    ]
    n_evidence = session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.nc_id == nc.id)
    )
    if not n_evidence:
        missing.append("at least one evidence file")
    if missing:
        raise WorkflowError(f"missing before submit: {', '.join(missing)}", 422)
    nc.submitted_at = clock.now()
    _transition(session, nc, actor, "nc.submit", NcStatus.PENDING_VERIFICATION)


def verify(
    session: Session,
    nc: NonConformance,
    user: User,
    actor: audit.Actor,
    approve: bool,
    note: str | None,
) -> None:
    _require_quality_head(user)
    if nc.status != NcStatus.PENDING_VERIFICATION:
        raise WorkflowError(f"cannot verify an NC in status {nc.status.value}")
    now = clock.now()
    if approve:
        nc.verified_by, nc.verified_at, nc.verification_note = user.id, now, note
        nc.closed_at = now
        _transition(session, nc, actor, "nc.verify", NcStatus.CLOSED, {"note": note})
    else:
        if not note or not note.strip():
            raise WorkflowError("a reason is required to reject", 422)
        nc.verification_note = note
        _transition(session, nc, actor, "nc.reject", NcStatus.IN_PROGRESS, {"reason": note})


def cancel(
    session: Session, nc: NonConformance, user: User, actor: audit.Actor, reason: str
) -> None:
    _require_quality_head(user)
    if nc.status not in CANCELLABLE:
        raise WorkflowError(f"cannot cancel an NC in status {nc.status.value}")
    if not reason or not reason.strip():
        raise WorkflowError("a reason is required to cancel", 422)
    nc.cancel_reason = reason
    _transition(session, nc, actor, "nc.cancel", NcStatus.CANCELLED, {"reason": reason})


def is_overdue(nc: NonConformance, today: date | None = None) -> bool:
    today = today or clock.now().date()
    return (
        nc.target_date is not None
        and nc.status not in (NcStatus.CLOSED, NcStatus.CANCELLED)
        and nc.target_date < today
    )
