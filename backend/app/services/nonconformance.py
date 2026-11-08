"""Non-conformance creation, owner resolution and recurrence linking (Section 10.1).

- One NC per Not OK part report, grouping all its Not OK characteristics.
- Recurrence, not floods: a Not OK on the same part + machine + characteristic while an NC is
  still open within `recurrence_window_hours` is linked to that NC (recurrence_count + 1) and a
  single RECURRENCE alert is sent, still with its own measured alert time.
- At `recurrence_escalate_at` recurrences (default 3) the NC escalates to the supervisor.
Runs inside the ingest transaction.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, events
from app.models import (
    Characteristic,
    InspectionReport,
    Machine,
    Measurement,
    NcMeasurement,
    NonConformance,
    Part,
    Process,
)
from app.models.enums import AlertKind, CharClass, NcStatus, ToleranceType
from app.services import audit, settings
from app.services.alerts import create_alert
from app.services.escalation import escalate
from app.services.notifications.templates import limits_text, nok_alert, over_text
from app.services.numbering import next_number
from app.services.ownership import resolve_owners

OPEN_STATES = (
    NcStatus.OPEN,
    NcStatus.ACKNOWLEDGED,
    NcStatus.IN_PROGRESS,
    NcStatus.PENDING_VERIFICATION,
)
_SEVERITY_RANK = {CharClass.STANDARD: 0, CharClass.SIGNIFICANT: 1, CharClass.CRITICAL: 2}


@dataclass
class NokItem:
    measurement: Measurement
    characteristic: Characteristic | None
    over_limit: object = None
    tolerance_type: ToleranceType = ToleranceType.BILATERAL


@dataclass
class NcOutcome:
    created: list[NonConformance] = field(default_factory=list)
    recurrences: list[NonConformance] = field(default_factory=list)
    alert_ids: list[uuid.UUID] = field(default_factory=list)


def _severity(items: list[NokItem]) -> CharClass:
    classes = [i.characteristic.classification for i in items if i.characteristic]
    return max(classes, key=_SEVERITY_RANK.__getitem__, default=CharClass.STANDARD)


def _line(item: NokItem) -> str:
    m = item.measurement
    c = item.characteristic
    name = c.name if c else (m.char_name or m.char_no)
    decimals = c.decimals if c else 3
    text = limits_text(name, item.tolerance_type, m.nominal, m.usl, m.lsl, decimals)
    suspect = " - possible probing/entry error, re-measure" if m.is_suspect else ""
    return f"{m.char_no} {text} → measured {m.actual:.{decimals}f}{over_text(item.over_limit, decimals)}{suspect}"  # type: ignore[arg-type]


def _find_open_nc(
    session: Session, report: InspectionReport, characteristic_id: uuid.UUID, since: datetime
) -> NonConformance | None:
    return session.scalars(
        select(NonConformance)
        .join(NcMeasurement, NcMeasurement.nc_id == NonConformance.id)
        .join(Measurement, Measurement.id == NcMeasurement.measurement_id)
        .where(
            NonConformance.part_id == report.part_id,
            NonConformance.machine_id == report.machine_id,
            NonConformance.status.in_(OPEN_STATES),
            NonConformance.detected_at >= since,
            Measurement.characteristic_id == characteristic_id,
        )
        .order_by(NonConformance.detected_at.desc())
        .limit(1)
    ).first()


def raise_for_report(session: Session, report: InspectionReport, items: list[NokItem]) -> NcOutcome:
    outcome = NcOutcome()
    if not items:
        return outcome

    since = clock.now() - timedelta(hours=settings.recurrence_window_hours(session))
    recurring: dict[uuid.UUID, tuple[NonConformance, list[NokItem]]] = {}
    fresh: list[NokItem] = []
    for item in items:
        nc = (
            _find_open_nc(session, report, item.characteristic.id, since)
            if item.characteristic
            else None
        )
        if nc is not None:
            recurring.setdefault(nc.id, (nc, []))[1].append(item)
        else:
            fresh.append(item)

    part = session.get(Part, report.part_id) if report.part_id else None
    machine = session.get(Machine, report.machine_id) if report.machine_id else None
    process = session.get(Process, report.process_id) if report.process_id else None
    process_text = f"{process.code} {process.name}" if process else None
    header = {
        "part_no": part.part_no if part else "?",
        "part_name": part.name if part else "",
        "serial_no": report.serial_no,
        "machine_code": machine.code if machine else None,
        "process_text": process_text,
    }

    for nc, linked in recurring.values():
        before = {"recurrence_count": nc.recurrence_count}
        nc.recurrence_count += 1
        for item in linked:
            session.add(NcMeasurement(nc_id=nc.id, measurement_id=item.measurement.id))
        title, body = nok_alert(
            prefix="RECURRENCE",
            lines=[_line(i) for i in linked],
            severity=nc.severity.value,
            nc_no=nc.nc_no,
            nc_id=nc.id,
            extra=[f"Recurrence #{nc.recurrence_count} on the open NC, report {report.report_no}."],
            **header,
        )
        alert = create_alert(
            session,
            kind=AlertKind.RECURRENCE,
            recipient_user_id=nc.owner_user_id,
            title=title,
            body=body,
            nc_id=nc.id,
            source_received_at=report.received_at,
        )
        outcome.alert_ids.append(alert.id)
        audit.record(
            session,
            actor=audit.SYSTEM,
            action="nc.recurrence",
            entity="nonconformance",
            entity_id=nc.id,
            before=before,
            after={"recurrence_count": nc.recurrence_count, "report_id": report.id},
        )
        if nc.recurrence_count >= settings.recurrence_escalate_at(session):
            escalate(session, nc, 1, f"{nc.recurrence_count} recurrences")
        events.publish(session, "nc.updated", id=nc.id)
        outcome.recurrences.append(nc)

    if fresh:
        owners = resolve_owners(
            session,
            machine_id=report.machine_id,
            process_id=report.process_id,
            part_id=report.part_id,
        )
        now = clock.now()
        nc = NonConformance(
            nc_no=next_number(session, NonConformance.nc_no, "NC", now, 5),
            part_id=report.part_id,
            machine_id=report.machine_id,
            process_id=report.process_id,
            first_report_id=report.id,
            severity=_severity(fresh),
            status=NcStatus.OPEN,
            owner_user_id=owners.owner_user_id,
            supervisor_user_id=owners.supervisor_user_id,
            detected_at=now,
            warnings=[{"code": "NO_OWNER", "message": owners.warning}] if owners.warning else [],
        )
        session.add(nc)
        session.flush()
        for item in fresh:
            session.add(NcMeasurement(nc_id=nc.id, measurement_id=item.measurement.id))
        extra = [f"Warning: {owners.warning}"] if owners.warning else []
        title, body = nok_alert(
            prefix="NOT OK",
            lines=[_line(i) for i in fresh],
            severity=nc.severity.value,
            nc_no=nc.nc_no,
            nc_id=nc.id,
            extra=extra,
            **header,
        )
        alert = create_alert(
            session,
            kind=AlertKind.NOK,
            recipient_user_id=owners.owner_user_id,
            title=title,
            body=body,
            nc_id=nc.id,
            source_received_at=report.received_at,
        )
        outcome.alert_ids.append(alert.id)
        audit.record(
            session,
            actor=audit.SYSTEM,
            action="nc.create",
            entity="nonconformance",
            entity_id=nc.id,
            after=audit.snapshot(nc) | {"owner_matched_by": owners.matched_by},
        )
        events.publish(session, "nc.updated", id=nc.id)
        outcome.created.append(nc)
    return outcome
