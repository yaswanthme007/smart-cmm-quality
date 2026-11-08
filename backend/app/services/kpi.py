"""KPI service (Section 13). Every KPI is computed from stored events, never typed in.

K1 inspected / OK / Not OK      K2 OK% / Not OK%          K3 alert generation time
K3b report latency              K4 open / pending / closed actions
K5 closure lead time            K6 trends, Pareto, NC ageing

Filters: date range, part, machine, process, shift. Report KPIs use the report's measured_at
(falling back to received_at); NC KPIs use detected_at.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Float, Select, and_, case, cast, func, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    Alert,
    Characteristic,
    InspectionReport,
    Machine,
    Measurement,
    NonConformance,
    Outbox,
    Part,
    Process,
)
from app.models.enums import AlertKind, NcStatus, ReportStatus, Result
from app.services import settings

OPEN = (NcStatus.OPEN, NcStatus.ACKNOWLEDGED)
PENDING = (NcStatus.IN_PROGRESS, NcStatus.PENDING_VERIFICATION)
DONE = (NcStatus.CLOSED, NcStatus.CANCELLED)


@dataclass(frozen=True)
class KpiFilter:
    date_from: datetime | None = None
    date_to: datetime | None = None
    part_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None
    process_id: uuid.UUID | None = None
    shift: str | None = None


def pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _report_time() -> ColumnElement[datetime]:
    return func.coalesce(InspectionReport.measured_at, InspectionReport.received_at)


def shift_expr(session: Session, ts: ColumnElement[datetime]) -> ColumnElement[str]:
    """SQL CASE mapping a timestamp to the configured shift name (plant local time)."""
    cfg = settings.get_value(session, "shifts") or {}
    tz = cfg.get("timezone", "Asia/Kolkata")
    shifts = sorted(cfg.get("list", []), key=lambda s: s["start"])
    if not shifts:
        return literal("ALL")
    local = func.timezone(tz, ts)
    minutes = cast(func.extract("hour", local) * 60 + func.extract("minute", local), Float)

    def m(hhmm: str) -> int:
        h, mi = hhmm.split(":")
        return int(h) * 60 + int(mi)

    whens = []
    for i, s in enumerate(shifts):
        start = m(s["start"])
        end = m(shifts[i + 1]["start"]) if i + 1 < len(shifts) else 24 * 60
        whens.append((and_(minutes >= start, minutes < end), literal(s["name"])))
    # Before the first shift start belongs to the last (overnight) shift.
    return case(*whens, else_=literal(shifts[-1]["name"]))


def _filter_reports(session: Session, q: Select[Any], f: KpiFilter) -> Select[Any]:
    t = _report_time()
    q = q.where(InspectionReport.status == ReportStatus.INGESTED)
    if f.date_from:
        q = q.where(t >= f.date_from)
    if f.date_to:
        q = q.where(t < f.date_to)
    if f.part_id:
        q = q.where(InspectionReport.part_id == f.part_id)
    if f.machine_id:
        q = q.where(InspectionReport.machine_id == f.machine_id)
    if f.process_id:
        q = q.where(InspectionReport.process_id == f.process_id)
    if f.shift:
        q = q.where(shift_expr(session, t) == f.shift)
    return q


def _filter_ncs(session: Session, q: Select[Any], f: KpiFilter) -> Select[Any]:
    if f.date_from:
        q = q.where(NonConformance.detected_at >= f.date_from)
    if f.date_to:
        q = q.where(NonConformance.detected_at < f.date_to)
    if f.part_id:
        q = q.where(NonConformance.part_id == f.part_id)
    if f.machine_id:
        q = q.where(NonConformance.machine_id == f.machine_id)
    if f.process_id:
        q = q.where(NonConformance.process_id == f.process_id)
    if f.shift:
        q = q.where(shift_expr(session, NonConformance.detected_at) == f.shift)
    return q


def _percentiles(
    session: Session, values: ColumnElement[Any], base: Select[Any], qs: list[float]
) -> list[float | None]:
    sub = base.add_columns(values.label("v")).subquery()
    cols = [func.percentile_cont(q).within_group(sub.c.v) for q in qs]
    row = session.execute(select(*cols, func.max(sub.c.v), func.count(sub.c.v))).one()
    return [float(x) if x is not None else None for x in row]


def summary(session: Session, f: KpiFilter) -> dict[str, Any]:
    r = InspectionReport
    k1 = session.execute(
        _filter_reports(
            session,
            select(
                func.count(r.id),
                func.count(r.id).filter(r.part_result == Result.OK),
                func.count(r.id).filter(r.part_result == Result.MARGINAL),
                func.count(r.id).filter(r.part_result == Result.NOK),
            ),
            f,
        )
    ).one()
    inspected, ok_only, marginal, nok = (int(x) for x in k1)
    ok = ok_only + marginal  # marginal parts count as conforming

    m = Measurement
    chars = session.execute(
        _filter_reports(
            session,
            select(func.count(m.id), func.count(m.id).filter(m.result == Result.NOK)).join(
                r, r.id == m.report_id
            ),
            f,
        )
    ).one()

    # K3: per Not OK result (NOK + RECURRENCE alerts) generation time
    alert_base = _alert_base(session, f)
    p50, p95, mx, n_alerts = _percentiles(session, Alert.generation_ms, alert_base, [0.5, 0.95])
    email_base = (
        _alert_base(session, f)
        .join(Outbox, Outbox.alert_id == Alert.id)
        .where(Outbox.sent_at.isnot(None))
    )
    e50, e95, emx, n_email = _percentiles(
        session,
        func.extract("epoch", Outbox.sent_at - Alert.source_received_at) * 1000,
        email_base,
        [0.5, 0.95],
    )

    # K3b: report latency received_at - measured_at (seconds), when measured_at was in the file
    lat_base = _filter_reports(session, select(r.id), f).where(
        r.measured_at.isnot(None), r.measured_at < r.received_at
    )
    l50, l95, lmx, n_lat = _percentiles(
        session, func.extract("epoch", r.received_at - r.measured_at), lat_base, [0.5, 0.95]
    )

    # K4
    nc = NonConformance
    today = datetime.now(UTC).date()
    k4 = session.execute(
        _filter_ncs(
            session,
            select(
                func.count(nc.id).filter(nc.status.in_(OPEN)),
                func.count(nc.id).filter(nc.status.in_(PENDING)),
                func.count(nc.id).filter(nc.status == NcStatus.CLOSED),
                func.count(nc.id).filter(nc.status == NcStatus.CANCELLED),
                func.count(nc.id).filter(nc.status.notin_(DONE), nc.target_date < today),
                func.count(nc.id).filter(nc.status.notin_(DONE), nc.escalation_level > 0),
            ),
            f,
        )
    ).one()

    # K5 (hours)
    closed_base = _filter_ncs(session, select(nc.id), f).where(nc.status == NcStatus.CLOSED)
    c50, c90, cmx, n_closed = _percentiles(
        session,
        func.extract("epoch", nc.closed_at - nc.detected_at) / 3600,
        closed_base,
        [0.5, 0.9],
    )
    on_time = (
        session.scalar(
            _filter_ncs(session, select(func.count(nc.id)), f).where(
                nc.status == NcStatus.CLOSED,
                nc.target_date.isnot(None),
                func.date(nc.closed_at) <= nc.target_date,
            )
        )
        or 0
    )
    ack_base = _filter_ncs(session, select(nc.id), f).where(nc.acknowledged_at.isnot(None))
    a50, a90, _amx, n_ack = _percentiles(
        session,
        func.extract("epoch", nc.acknowledged_at - nc.detected_at) / 60,
        ack_base,
        [0.5, 0.9],
    )

    return {
        "k1": {
            "inspected": inspected,
            "ok": ok,
            "ok_only": ok_only,
            "marginal": marginal,
            "nok": nok,
        },
        "k2": {
            "ok_pct": pct(ok, inspected),
            "nok_pct": pct(nok, inspected),
            "marginal_pct": pct(marginal, inspected),
            "characteristics_measured": int(chars[0]),
            "characteristics_nok": int(chars[1]),
            "characteristic_nok_pct": pct(int(chars[1]), int(chars[0])),
        },
        "k3": {
            "count": int(n_alerts or 0),
            "median_ms": _round(p50),
            "p95_ms": _round(p95),
            "max_ms": _round(mx),
            "email_count": int(n_email or 0),
            "email_median_ms": _round(e50),
            "email_p95_ms": _round(e95),
            "email_max_ms": _round(emx),
        },
        "k3b": {
            "count": int(n_lat or 0),
            "median_s": _round(l50),
            "p95_s": _round(l95),
            "max_s": _round(lmx),
        },
        "k4": {
            "open": int(k4[0]),
            "pending": int(k4[1]),
            "closed": int(k4[2]),
            "cancelled": int(k4[3]),
            "overdue": int(k4[4]),
            "escalated_open": int(k4[5]),
        },
        "k5": {
            "closed_count": int(n_closed or 0),
            "median_h": _round(c50, 2),
            "p90_h": _round(c90, 2),
            "max_h": _round(cmx, 2),
            "closed_on_time_pct": pct(int(on_time), int(n_closed or 0)),
            "ack_count": int(n_ack or 0),
            "ack_median_min": _round(a50, 2),
            "ack_p90_min": _round(a90, 2),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "demo_data": True,
    }


def _round(x: float | None, nd: int = 0) -> float | None:
    if x is None:
        return None
    return round(x, nd) if nd else float(round(x))


def _alert_base(session: Session, f: KpiFilter) -> Select[Any]:
    q = (
        select(Alert.id)
        .join(NonConformance, NonConformance.id == Alert.nc_id)
        .where(
            Alert.kind.in_([AlertKind.NOK, AlertKind.RECURRENCE]), Alert.generation_ms.isnot(None)
        )
    )
    if f.date_from:
        q = q.where(Alert.created_at >= f.date_from)
    if f.date_to:
        q = q.where(Alert.created_at < f.date_to)
    if f.part_id:
        q = q.where(NonConformance.part_id == f.part_id)
    if f.machine_id:
        q = q.where(NonConformance.machine_id == f.machine_id)
    if f.process_id:
        q = q.where(NonConformance.process_id == f.process_id)
    if f.shift:
        q = q.where(shift_expr(session, Alert.created_at) == f.shift)
    return q


def alert_times(session: Session, f: KpiFilter, limit: int = 500) -> list[dict[str, Any]]:
    """K3 list view: every Not OK alert with its generation time."""
    ids = _alert_base(session, f).subquery()
    rows = session.execute(
        select(Alert, NonConformance.nc_no, Outbox.sent_at)
        .join(ids, ids.c.id == Alert.id)
        .join(NonConformance, NonConformance.id == Alert.nc_id)
        .outerjoin(Outbox, Outbox.alert_id == Alert.id)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    ).all()
    out = []
    for a, nc_no, sent_at in rows:
        email_ms = None
        if sent_at and a.source_received_at:
            email_ms = int((sent_at - a.source_received_at).total_seconds() * 1000)
        out.append(
            {
                "alert_id": str(a.id),
                "nc_id": str(a.nc_id),
                "nc_no": nc_no,
                "kind": a.kind.value,
                "title": a.title,
                "source_received_at": a.source_received_at.isoformat()
                if a.source_received_at
                else None,
                "created_at": a.created_at.isoformat(),
                "generation_ms": a.generation_ms,
                "email_sent_at": sent_at.isoformat() if sent_at else None,
                "email_ms": email_ms,
            }
        )
    return out


GROUPS = {
    "machine": (InspectionReport.machine_id, Machine, Machine.code),
    "part": (InspectionReport.part_id, Part, Part.part_no),
    "process": (InspectionReport.process_id, Process, Process.code),
}


def trends(
    session: Session, f: KpiFilter, granularity: str = "day", group_by: str = "none"
) -> list[dict[str, Any]]:
    """K6: Not OK % per day/week, optionally per machine / part / process."""
    t = func.timezone("Asia/Kolkata", _report_time())
    bucket = func.date_trunc("week" if granularity == "week" else "day", t).label("bucket")
    r = InspectionReport
    cols: list[Any] = [
        bucket,
        func.count(r.id).label("inspected"),
        func.count(r.id).filter(r.part_result == Result.NOK).label("nok"),
        func.count(r.id).filter(r.part_result == Result.MARGINAL).label("marginal"),
    ]
    q = select(*cols)
    group_cols: list[Any] = [bucket]
    if group_by in GROUPS:
        fk, model, label = GROUPS[group_by]
        q = q.add_columns(label.label("group")).join(model, model.id == fk)
        group_cols.append(label)
    q = _filter_reports(session, q, f).group_by(*group_cols).order_by(bucket)
    out = []
    for row in session.execute(q).mappings():
        out.append(
            {
                "bucket": row["bucket"].date().isoformat(),
                "group": row.get("group"),
                "inspected": row["inspected"],
                "nok": row["nok"],
                "marginal": row["marginal"],
                "nok_pct": pct(row["nok"], row["inspected"]),
            }
        )
    return out


def pareto(session: Session, f: KpiFilter, limit: int = 15) -> list[dict[str, Any]]:
    """K6: Not OK characteristics, most frequent first, with cumulative %."""
    m, r, c, p = Measurement, InspectionReport, Characteristic, Part
    q = (
        select(
            p.part_no, m.char_no, func.max(c.name).label("name"), func.count(m.id).label("count")
        )
        .join(r, r.id == m.report_id)
        .join(p, p.id == r.part_id)
        .outerjoin(c, c.id == m.characteristic_id)
        .where(m.result == Result.NOK)
        .group_by(p.part_no, m.char_no)
        .order_by(func.count(m.id).desc(), p.part_no, m.char_no)
    )
    rows = session.execute(_filter_reports(session, q, f)).all()
    total = sum(row.count for row in rows)
    out, running = [], 0
    for row in rows[:limit]:
        running += row.count
        out.append(
            {
                "part_no": row.part_no,
                "char_no": row.char_no,
                "name": row.name,
                "label": f"{row.part_no} {row.char_no}",
                "count": row.count,
                "cumulative_pct": pct(running, total),
            }
        )
    return out


AGE_BUCKETS = [("0-1 d", 0, 1), ("1-3 d", 1, 3), ("3-7 d", 3, 7), ("> 7 d", 7, None)]


def ageing(session: Session, f: KpiFilter, now: datetime | None = None) -> list[dict[str, Any]]:
    """K6: open (not closed / cancelled) NCs by age."""
    now = now or datetime.now(UTC)
    nc = NonConformance
    detected = list(
        session.scalars(
            _filter_ncs(session, select(nc.detected_at), f).where(nc.status.notin_(DONE))
        )
    )
    out = []
    for label, lo, hi in AGE_BUCKETS:
        n = sum(
            1
            for d in detected
            if now - d >= timedelta(days=lo) and (hi is None or now - d < timedelta(days=hi))
        )
        out.append({"bucket": label, "count": n})
    return out


def by_dimension(session: Session, f: KpiFilter, group_by: str) -> list[dict[str, Any]]:
    """Not OK count and % per machine / part / process (dashboard bar chart)."""
    fk, model, label = GROUPS[group_by]
    r = InspectionReport
    q = (
        select(
            label.label("group"),
            model.id.label("id"),
            func.count(r.id).label("inspected"),
            func.count(r.id).filter(r.part_result == Result.NOK).label("nok"),
        )
        .join(model, model.id == fk)
        .group_by(label, model.id)
        .order_by(label)
    )
    return [
        {
            "group": row.group,
            "id": str(row.id),
            "inspected": row.inspected,
            "nok": row.nok,
            "nok_pct": pct(row.nok, row.inspected),
        }
        for row in session.execute(_filter_reports(session, q, f))
    ]


def parse_date(d: date | None, end: bool = False) -> datetime | None:
    if d is None:
        return None
    from zoneinfo import ZoneInfo

    start = datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("Asia/Kolkata"))
    return (start + timedelta(days=1) if end else start).astimezone(UTC)
