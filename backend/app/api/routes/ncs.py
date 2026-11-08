"""Non-conformance API: list, detail, timeline and the corrective-action workflow (Section 14)."""

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_actor, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.models import (
    Alert,
    AuditLog,
    Characteristic,
    Evidence,
    InspectionReport,
    Machine,
    Measurement,
    NcMeasurement,
    NonConformance,
    Outbox,
    Part,
    Process,
    User,
)
from app.models.enums import CharClass, NcStatus, Result, RootCauseCategory
from app.services import audit, capa

router = APIRouter(prefix="/ncs", tags=["non-conformances"])


class NcOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nc_no: str
    part_id: uuid.UUID | None
    machine_id: uuid.UUID | None
    process_id: uuid.UUID | None
    first_report_id: uuid.UUID
    severity: CharClass
    status: NcStatus
    owner_user_id: uuid.UUID | None
    supervisor_user_id: uuid.UUID | None
    detected_at: datetime
    acknowledged_at: datetime | None
    escalation_level: int
    target_date: date | None
    containment: str | None
    root_cause_category: RootCauseCategory | None
    root_cause: str | None
    corrective_action: str | None
    preventive_action: str | None
    submitted_at: datetime | None
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    verification_note: str | None
    closed_at: datetime | None
    cancel_reason: str | None
    recurrence_count: int
    warnings: list[dict[str, Any]]
    part_no: str | None = None
    part_name: str | None = None
    machine_code: str | None = None
    process_code: str | None = None
    owner_name: str | None = None
    supervisor_name: str | None = None
    overdue: bool = False
    age_hours: float = 0
    characteristics: list[str] = []
    can_work: bool = False


class NcMeasurementOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    report_no: str
    serial_no: str | None
    char_no: str
    char_name: str | None
    actual: Decimal
    nominal: Decimal | None
    usl: Decimal | None
    lsl: Decimal | None
    deviation: Decimal | None
    result: Result
    is_suspect: bool
    measured_at: datetime | None
    classification: str | None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime: str
    size: int
    note: str | None
    uploaded_by: uuid.UUID | None
    created_at: datetime


class NcDetail(NcOut):
    measurements: list[NcMeasurementOut] = []
    evidence: list[EvidenceOut] = []
    reinspection_ok_report: dict[str, Any] | None = None


class NcPage(BaseModel):
    total: int
    items: list[NcOut]


class TimelineEvent(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: str | None = None
    actor: str | None = None
    ms: int | None = None


class NcPatch(BaseModel):
    containment: str | None = None
    root_cause_category: RootCauseCategory | None = None
    root_cause: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    target_date: date | None = None


class VerifyIn(BaseModel):
    approve: bool
    note: str | None = None


class CancelIn(BaseModel):
    reason: str


def _names(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(ids)))}


def nc_out(db: Session, nc: NonConformance, user: User, cls: type[NcOut] = NcOut) -> NcOut:
    out = cls.model_validate(nc)
    if nc.part_id and (p := db.get(Part, nc.part_id)):
        out.part_no, out.part_name = p.part_no, p.name
    if nc.machine_id and (m := db.get(Machine, nc.machine_id)):
        out.machine_code = m.code
    if nc.process_id and (pr := db.get(Process, nc.process_id)):
        out.process_code = f"{pr.code} {pr.name}"
    names = _names(db, {nc.owner_user_id, nc.supervisor_user_id})
    out.owner_name = names.get(nc.owner_user_id) if nc.owner_user_id else None
    out.supervisor_name = names.get(nc.supervisor_user_id) if nc.supervisor_user_id else None
    out.overdue = capa.is_overdue(nc)
    end = nc.closed_at or datetime.now(UTC)
    out.age_hours = round((end - nc.detected_at).total_seconds() / 3600, 2)
    out.characteristics = sorted(
        set(
            db.scalars(
                select(Measurement.char_no)
                .join(NcMeasurement, NcMeasurement.measurement_id == Measurement.id)
                .where(NcMeasurement.nc_id == nc.id)
            )
        )
    )
    out.can_work = capa.can_work(user, nc)
    return out


@router.get("", response_model=NcPage)
def list_ncs(
    status: list[NcStatus] | None = Query(None),
    bucket: str | None = Query(None, pattern="^(open|pending|closed|cancelled|overdue)$"),
    severity: CharClass | None = None,
    owner_user_id: uuid.UUID | None = None,
    machine_id: uuid.UUID | None = None,
    part_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    mine: bool = False,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NcPage:
    query = select(NonConformance)
    buckets = {
        "open": [NcStatus.OPEN, NcStatus.ACKNOWLEDGED],
        "pending": [NcStatus.IN_PROGRESS, NcStatus.PENDING_VERIFICATION],
        "closed": [NcStatus.CLOSED],
        "cancelled": [NcStatus.CANCELLED],
    }
    if bucket == "overdue":
        query = query.where(
            NonConformance.target_date < datetime.now(UTC).date(),
            NonConformance.status.notin_([NcStatus.CLOSED, NcStatus.CANCELLED]),
        )
    elif bucket:
        query = query.where(NonConformance.status.in_(buckets[bucket]))
    if status:
        query = query.where(NonConformance.status.in_(status))
    if severity:
        query = query.where(NonConformance.severity == severity)
    if owner_user_id:
        query = query.where(NonConformance.owner_user_id == owner_user_id)
    if mine:
        query = query.where(
            or_(
                NonConformance.owner_user_id == user.id,
                NonConformance.supervisor_user_id == user.id,
            )
        )
    if machine_id:
        query = query.where(NonConformance.machine_id == machine_id)
    if part_id:
        query = query.where(NonConformance.part_id == part_id)
    if process_id:
        query = query.where(NonConformance.process_id == process_id)
    if date_from:
        query = query.where(NonConformance.detected_at >= date_from)
    if date_to:
        query = query.where(NonConformance.detected_at < date_to)
    if q:
        query = query.where(NonConformance.nc_no.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(NonConformance.detected_at.desc()).limit(limit).offset(offset))
    return NcPage(total=total, items=[nc_out(db, nc, user) for nc in rows])


def _get(db: Session, nc_id: uuid.UUID) -> NonConformance:
    nc = db.get(NonConformance, nc_id)
    if nc is None:
        raise HTTPException(404, "NC not found")
    return nc


def nc_detail(db: Session, nc: NonConformance, user: User) -> NcDetail:
    out = nc_out(db, nc, user, NcDetail)
    assert isinstance(out, NcDetail)
    rows = db.execute(
        select(Measurement, InspectionReport, Characteristic)
        .join(NcMeasurement, NcMeasurement.measurement_id == Measurement.id)
        .join(InspectionReport, InspectionReport.id == Measurement.report_id)
        .outerjoin(Characteristic, Characteristic.id == Measurement.characteristic_id)
        .where(NcMeasurement.nc_id == nc.id)
        .order_by(InspectionReport.received_at, Measurement.char_no)
    ).all()
    out.measurements = [
        NcMeasurementOut(
            id=m.id,
            report_id=r.id,
            report_no=r.report_no,
            serial_no=r.serial_no,
            char_no=m.char_no,
            char_name=m.char_name,
            actual=m.actual,
            nominal=m.nominal,
            usl=m.usl,
            lsl=m.lsl,
            deviation=m.deviation,
            result=m.result,
            is_suspect=m.is_suspect,
            measured_at=m.measured_at,
            classification=c.classification.value if c else None,
        )
        for m, r, c in rows
    ]
    out.evidence = [
        EvidenceOut.model_validate(e)
        for e in db.scalars(
            select(Evidence).where(Evidence.nc_id == nc.id).order_by(Evidence.created_at)
        )
    ]
    first = db.get(InspectionReport, nc.first_report_id)
    if first is not None and first.serial_no:
        reinspected = db.scalars(
            select(InspectionReport)
            .where(
                InspectionReport.part_id == first.part_id,
                InspectionReport.serial_no == first.serial_no,
                InspectionReport.received_at > first.received_at,
                InspectionReport.part_result.in_([Result.OK, Result.MARGINAL]),
            )
            .order_by(InspectionReport.received_at.desc())
        ).first()
        if reinspected is not None:
            out.reinspection_ok_report = {
                "id": str(reinspected.id),
                "report_no": reinspected.report_no,
                "part_result": reinspected.part_result.value if reinspected.part_result else None,
                "received_at": reinspected.received_at.isoformat(),
            }
    return out


@router.get("/{nc_id}", response_model=NcDetail)
def get_nc(
    nc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> NcDetail:
    return nc_detail(db, _get(db, nc_id), user)


ACTION_TITLES = {
    "nc.create": "Detected, NC opened",
    "nc.recurrence": "Recurrence linked",
    "nc.escalate": "Escalated",
    "nc.acknowledge": "Acknowledged",
    "nc.update": "Actions updated",
    "nc.start": "In progress",
    "nc.evidence": "Evidence added",
    "nc.submit": "Submitted for verification",
    "nc.verify": "Verified and closed",
    "nc.reject": "Rejected, back to in progress",
    "nc.cancel": "Cancelled",
}


@router.get("/{nc_id}/timeline", response_model=list[TimelineEvent])
def timeline(
    nc_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[TimelineEvent]:
    """detected -> alerted (ms) -> escalated -> acknowledged -> actions -> verified -> closed."""
    nc = _get(db, nc_id)
    out: list[TimelineEvent] = []
    first = db.get(InspectionReport, nc.first_report_id)
    if first is not None:
        if first.measured_at:
            out.append(
                TimelineEvent(
                    at=first.measured_at,
                    kind="measured",
                    title=f"Measured on CMM ({first.report_no})",
                )
            )
        out.append(
            TimelineEvent(
                at=first.received_at,
                kind="received",
                title="Report received",
                detail=first.original_filename,
            )
        )
    alerts = db.scalars(select(Alert).where(Alert.nc_id == nc.id).order_by(Alert.created_at)).all()
    names = _names(db, {a.recipient_user_id for a in alerts})
    for a in alerts:
        out.append(
            TimelineEvent(
                at=a.created_at,
                kind=f"alert.{a.kind.value.lower()}",
                title=f"{a.kind.value} alert to {names.get(a.recipient_user_id, '?')}"
                if a.recipient_user_id
                else f"{a.kind.value} alert",
                detail=a.title,
                ms=a.generation_ms,
            )
        )
        email = db.scalars(select(Outbox).where(Outbox.alert_id == a.id)).first()
        if email is not None and email.sent_at is not None:
            ms = (
                int((email.sent_at - a.source_received_at).total_seconds() * 1000)
                if a.source_received_at
                else None
            )
            out.append(
                TimelineEvent(
                    at=email.sent_at,
                    kind="email.sent",
                    title=f"Email sent to {email.payload.get('to')}",
                    ms=ms,
                )
            )
    entries = db.execute(
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.entity == "nonconformance", AuditLog.entity_id == str(nc.id))
        .order_by(AuditLog.id)
    ).all()
    for entry, name in entries:
        detail = None
        if entry.after:
            keep = {
                k: v for k, v in entry.after.items() if k not in ("status",) and v not in (None, "")
            }
            if entry.action == "nc.create":
                keep = {"owner matched by": entry.after.get("owner_matched_by")}
            detail = "; ".join(f"{k}: {v}" for k, v in keep.items()) or None
        out.append(
            TimelineEvent(
                at=entry.at,
                kind=entry.action,
                title=ACTION_TITLES.get(entry.action, entry.action),
                detail=detail,
                actor=name or entry.actor_role,
            )
        )
    out.sort(key=lambda e: e.at)
    return out


def _run(fn: Callable[[], Any], db: Session) -> None:
    try:
        fn()
    except capa.PermissionDenied as exc:
        db.rollback()
        raise HTTPException(403, str(exc)) from exc
    except capa.WorkflowError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.message) from exc
    db.commit()


@router.post("/{nc_id}/acknowledge", response_model=NcDetail)
def acknowledge(
    nc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> NcDetail:
    nc = _get(db, nc_id)
    _run(lambda: capa.acknowledge(db, nc, user, actor), db)
    return nc_detail(db, nc, user)


@router.patch("/{nc_id}", response_model=NcDetail)
def patch_nc(
    nc_id: uuid.UUID,
    body: NcPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> NcDetail:
    nc = _get(db, nc_id)
    changes = body.model_dump(exclude_unset=True)
    _run(lambda: capa.update_actions(db, nc, user, actor, changes), db)
    return nc_detail(db, nc, user)


@router.post("/{nc_id}/evidence", response_model=EvidenceOut, status_code=201)
async def upload_evidence(
    nc_id: uuid.UUID,
    file: UploadFile = File(...),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> Evidence:
    nc = _get(db, nc_id)
    data = await file.read()
    holder: list[Evidence] = []
    _run(
        lambda: holder.append(
            capa.add_evidence(db, nc, user, actor, file.filename or "evidence", data, note)
        ),
        db,
    )
    return holder[0]


@router.get("/{nc_id}/evidence/{evidence_id}")
def download_evidence(
    nc_id: uuid.UUID,
    evidence_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    ev = db.get(Evidence, evidence_id)
    if ev is None or ev.nc_id != nc_id:
        raise HTTPException(404, "evidence not found")
    return FileResponse(
        get_settings().data_dir / ev.storage_path, media_type=ev.mime, filename=ev.filename
    )


@router.post("/{nc_id}/submit", response_model=NcDetail)
def submit(
    nc_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> NcDetail:
    nc = _get(db, nc_id)
    _run(lambda: capa.submit(db, nc, user, actor), db)
    return nc_detail(db, nc, user)


@router.post("/{nc_id}/verify", response_model=NcDetail)
def verify(
    nc_id: uuid.UUID,
    body: VerifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> NcDetail:
    nc = _get(db, nc_id)
    _run(lambda: capa.verify(db, nc, user, actor, body.approve, body.note), db)
    return nc_detail(db, nc, user)


@router.post("/{nc_id}/cancel", response_model=NcDetail)
def cancel(
    nc_id: uuid.UUID,
    body: CancelIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> NcDetail:
    nc = _get(db, nc_id)
    _run(lambda: capa.cancel(db, nc, user, actor, body.reason), db)
    return nc_detail(db, nc, user)
