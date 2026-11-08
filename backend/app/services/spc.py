"""SPC engine (Section 12): I-MR limits, Nelson rules, capability. Stream = (characteristic, machine).

Pure math functions at the top (golden-tested), database glue at the bottom. Control limits are
frozen from a baseline; only the Quality Head recalculates them (audited).
"""

import itertools
import statistics
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, events
from app.models import Characteristic, Machine, Measurement, Part, SpcLimits, SpcSignal
from app.models.enums import AlertKind, Result, SpcSignalStatus, ToleranceType
from app.services import audit, settings
from app.services.alerts import create_alert
from app.services.ownership import resolve_owners

D2 = 1.128  # d2 for moving ranges of n = 2
E2 = 2.66  # 3 / d2
D4 = 3.267  # MR chart upper factor for n = 2
BASELINE_N = 25
CAPABILITY_MIN_N = 30
CLEAR_AFTER = 9
ALL_RULES = ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"]

RULE_TEXT = {
    "N1": "1 point beyond 3σ (sudden event: chip, crash, probe error)",
    "N2": "9 points in a row on one side of the centre line (shift: offset change, new insert)",
    "N3": "6 points in a row steadily increasing or decreasing (tool wear / thermal drift)",
    "N4": "14 points in a row alternating up and down",
    "N5": "2 of 3 points beyond 2σ on the same side (early shift)",
    "N6": "4 of 5 points beyond 1σ on the same side",
    "N7": "15 points in a row within 1σ (stratification)",
    "N8": "8 points in a row beyond 1σ on either side (mixture)",
}


# ---------------------------------------------------------------- pure math


@dataclass(frozen=True)
class ImrLimits:
    center: float
    mr_bar: float
    sigma: float
    ucl: float
    lcl: float
    ucl_mr: float
    n: int


def imr_limits(values: Sequence[float]) -> ImrLimits:
    if len(values) < 2:
        raise ValueError("need at least 2 values for I-MR limits")
    center = statistics.fmean(values)
    mrs = [abs(b - a) for a, b in itertools.pairwise(values)]
    mr_bar = statistics.fmean(mrs)
    return ImrLimits(
        center=center,
        mr_bar=mr_bar,
        sigma=mr_bar / D2,
        ucl=center + E2 * mr_bar,
        lcl=center - E2 * mr_bar,
        ucl_mr=D4 * mr_bar,
        n=len(values),
    )


def _zones(x: float, center: float, sigma: float) -> float:
    return (x - center) / sigma if sigma > 0 else 0.0


def rules_at(
    values: Sequence[float], center: float, sigma: float, rules: Sequence[str]
) -> list[tuple[str, list[int]]]:
    """Rules triggered by the LAST point of `values`, with the indices of the pattern points."""
    n = len(values)
    if n == 0:
        return []
    z = [_zones(x, center, sigma) for x in values]
    i = n - 1
    hits: list[tuple[str, list[int]]] = []

    def window(k: int) -> list[int] | None:
        return list(range(n - k, n)) if n >= k else None

    if "N1" in rules and abs(z[i]) > 3:
        hits.append(("N1", [i]))
    w = window(9)
    if "N2" in rules and w and (all(z[j] > 0 for j in w) or all(z[j] < 0 for j in w)):
        hits.append(("N2", w))
    if "N3" in rules and (w := window(6)):
        diffs = [values[j] - values[j - 1] for j in w[1:]]
        if all(d > 0 for d in diffs) or all(d < 0 for d in diffs):
            hits.append(("N3", w))
    if "N4" in rules and (w := window(14)):
        diffs = [values[j] - values[j - 1] for j in w[1:]]
        if all(d != 0 for d in diffs) and all(a * b < 0 for a, b in itertools.pairwise(diffs)):
            hits.append(("N4", w))
    if "N5" in rules and (w := window(3)) and abs(z[i]) > 2:
        side = 1 if z[i] > 0 else -1
        beyond = [j for j in w if z[j] * side > 2]
        if len(beyond) >= 2:
            hits.append(("N5", beyond))
    if "N6" in rules and (w := window(5)) and abs(z[i]) > 1:
        side = 1 if z[i] > 0 else -1
        beyond = [j for j in w if z[j] * side > 1]
        if len(beyond) >= 4:
            hits.append(("N6", beyond))
    if "N7" in rules and (w := window(15)) and all(abs(z[j]) < 1 for j in w):
        hits.append(("N7", w))
    if "N8" in rules and (w := window(8)) and all(abs(z[j]) > 1 for j in w):
        hits.append(("N8", w))
    return hits


def rules_anywhere(
    values: Sequence[float], center: float, sigma: float, rules: Sequence[str]
) -> list[tuple[str, int]]:
    """(rule, index) for every point where a rule triggers; used to mark points on the chart."""
    marks = []
    for k in range(1, len(values) + 1):
        for rule, _ in rules_at(values[:k], center, sigma, rules):
            marks.append((rule, k - 1))
    return marks


@dataclass(frozen=True)
class Capability:
    valid: bool
    message: str | None
    n: int
    cp: float | None = None
    cpk: float | None = None
    pp: float | None = None
    ppk: float | None = None


def capability(
    values: Sequence[float],
    usl: float | None,
    lsl: float | None,
    sigma_within: float | None,
    active_signals: int,
) -> Capability:
    """Section 12.3: show only with n >= 30 and no active signals (Section 6 D17)."""
    n = len(values)
    if n < CAPABILITY_MIN_N:
        return Capability(False, f"Insufficient data ({n} of {CAPABILITY_MIN_N} readings)", n)
    if active_signals:
        return Capability(False, "Process not stable, capability not valid", n)
    if not sigma_within or sigma_within <= 0:
        return Capability(False, "No within-process variation", n)
    mean = statistics.fmean(values)
    sigma_overall = statistics.stdev(values)

    def indices(sigma: float) -> tuple[float | None, float]:
        sides = []
        if usl is not None:
            sides.append((usl - mean) / (3 * sigma))
        if lsl is not None:
            sides.append((mean - lsl) / (3 * sigma))
        both = (usl - lsl) / (6 * sigma) if usl is not None and lsl is not None else None
        return both, min(sides)

    cp, cpk = indices(sigma_within)
    pp, ppk = indices(sigma_overall) if sigma_overall > 0 else (None, None)
    return Capability(True, None, n, cp, cpk, pp, ppk)


# ---------------------------------------------------------------- database glue


def stream_points(
    session: Session,
    characteristic_id: uuid.UUID,
    machine_id: uuid.UUID | None,
    limit: int | None = None,
) -> list[Measurement]:
    q = select(Measurement).where(
        Measurement.characteristic_id == characteristic_id, Measurement.machine_id == machine_id
    )
    if limit:
        rows = session.scalars(
            q.order_by(Measurement.measured_at.desc(), Measurement.created_at.desc()).limit(limit)
        ).all()
        return list(reversed(rows))
    return list(session.scalars(q.order_by(Measurement.measured_at, Measurement.created_at)))


def active_limits(
    session: Session, characteristic_id: uuid.UUID, machine_id: uuid.UUID | None
) -> SpcLimits | None:
    return session.scalars(
        select(SpcLimits).where(
            SpcLimits.characteristic_id == characteristic_id,
            SpcLimits.machine_id == machine_id,
            SpcLimits.is_active,
        )
    ).first()


def set_baseline(
    session: Session,
    characteristic_id: uuid.UUID,
    machine_id: uuid.UUID | None,
    actor: audit.Actor,
    points: list[Measurement] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SpcLimits | None:
    """Freeze limits from conforming readings (first 25, or the chosen date range)."""
    if points is None:
        points = [
            m
            for m in stream_points(session, characteristic_id, machine_id)
            if m.result != Result.NOK
            and (date_from is None or (m.measured_at and m.measured_at >= date_from))
            and (date_to is None or (m.measured_at and m.measured_at <= date_to))
        ]
        if date_from is None and date_to is None:
            points = points[:BASELINE_N]
    if len(points) < 2:
        return None
    lim = imr_limits([float(m.actual) for m in points])
    old = active_limits(session, characteristic_id, machine_id)
    before = audit.snapshot(old) if old else None
    if old:
        old.is_active = False
    new = SpcLimits(
        characteristic_id=characteristic_id,
        machine_id=machine_id,
        center=Decimal(repr(lim.center)),
        ucl=Decimal(repr(lim.ucl)),
        lcl=Decimal(repr(lim.lcl)),
        mr_bar=Decimal(repr(lim.mr_bar)),
        sigma_within=Decimal(repr(lim.sigma)),
        n_baseline=lim.n,
        baseline_from=points[0].measured_at,
        baseline_to=points[-1].measured_at,
        frozen_by=actor.user_id,
        is_active=True,
    )
    session.add(new)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="spc.baseline",
        entity="spc_limits",
        entity_id=new.id,
        before=before,
        after=audit.snapshot(new),
    )
    return new


def _signal_alert(
    session: Session, signal: SpcSignal, char: Characteristic, machine: Machine | None
) -> None:
    part = session.get(Part, char.part_id)
    owners = resolve_owners(
        session,
        machine_id=machine.id if machine else None,
        process_id=machine.process_id if machine else char.process_id,
        part_id=char.part_id,
    )
    where = machine.code if machine else "all machines"
    title = f"[SPC WARNING] {part.part_no if part else ''} {char.char_no} {char.name} on {where}: {signal.rule}"
    body = "\n".join(
        [
            title,
            f"Rule {signal.rule}: {RULE_TEXT.get(signal.rule, '')}.",
            "Parts are still in tolerance; act before they fail (warned before it failed).",
            "Low priority: no escalation.",
            "Demo data: synthetic prototype.",
        ]
    )
    create_alert(
        session,
        kind=AlertKind.SPC_WARNING,
        recipient_user_id=owners.owner_user_id,
        title=title,
        body=body,
        spc_signal_id=signal.id,
        email=False,
    )


def evaluate_stream(
    session: Session, char: Characteristic, machine_id: uuid.UUID | None, rules: list[str]
) -> list[SpcSignal]:
    """Check the newest point of one stream; open new signals and clear recovered ones."""
    limits = active_limits(session, char.id, machine_id)
    if limits is None:
        conforming = [
            m for m in stream_points(session, char.id, machine_id) if m.result != Result.NOK
        ]
        if len(conforming) < BASELINE_N:
            return []
        limits = set_baseline(
            session, char.id, machine_id, audit.SYSTEM, points=conforming[:BASELINE_N]
        )
        if limits is None:
            return []
    window = stream_points(session, char.id, machine_id, limit=15)
    values = [float(m.actual) for m in window]
    hits = rules_at(values, float(limits.center), float(limits.sigma_within), rules)
    active = {
        s.rule: s
        for s in session.scalars(
            select(SpcSignal).where(
                SpcSignal.characteristic_id == char.id,
                SpcSignal.machine_id == machine_id,
                SpcSignal.status != SpcSignalStatus.CLEARED,
            )
        )
    }
    created = []
    machine = session.get(Machine, machine_id) if machine_id else None
    for rule, idx in hits:
        if rule in active:
            active[rule].in_control_streak = 0
            continue
        signal = SpcSignal(
            characteristic_id=char.id,
            machine_id=machine_id,
            rule=rule,
            measurement_ids=[str(window[j].id) for j in idx],
            status=SpcSignalStatus.ACTIVE,
            triggered_at=window[-1].measured_at or clock.now(),
        )
        session.add(signal)
        session.flush()
        _signal_alert(session, signal, char, machine)
        audit.record(
            session,
            actor=audit.SYSTEM,
            action="spc.signal",
            entity="spc_signal",
            entity_id=signal.id,
            after=audit.snapshot(signal),
        )
        events.publish(
            session,
            "spc.signal",
            id=signal.id,
            characteristic_id=char.id,
            machine_id=machine_id,
            rule=rule,
        )
        created.append(signal)
    if not hits:
        for signal in active.values():
            signal.in_control_streak += 1
            if signal.in_control_streak >= CLEAR_AFTER:
                signal.status = SpcSignalStatus.CLEARED
                audit.record(
                    session,
                    actor=audit.SYSTEM,
                    action="spc.clear",
                    entity="spc_signal",
                    entity_id=signal.id,
                    after={"status": "CLEARED"},
                )
    return created


def evaluate_streams(session: Session, measurements: list[Measurement]) -> list[SpcSignal]:
    rules = settings.spc_rules_enabled(session)
    created: list[SpcSignal] = []
    seen = set()
    for m in measurements:
        if m.characteristic_id is None or m.is_suspect:
            continue
        key = (m.characteristic_id, m.machine_id)
        if key in seen:
            continue
        seen.add(key)
        char = session.get(Characteristic, m.characteristic_id)
        if char is not None:
            created += evaluate_stream(session, char, m.machine_id, rules)
    return created


def spec_limits(char: Characteristic) -> tuple[float | None, float | None]:
    usl = (
        float(char.usl)
        if char.usl is not None and char.tolerance_type != ToleranceType.LOWER_ONLY
        else None
    )
    lsl = (
        float(char.lsl)
        if char.lsl is not None and char.tolerance_type != ToleranceType.UPPER_ONLY
        else None
    )
    return usl, lsl
