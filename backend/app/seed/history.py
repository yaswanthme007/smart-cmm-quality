"""30 days of SYNTHETIC history inserted through the real service layer (Section 18.2/18.3).

Every report goes through `ingest_parsed`, so classification, NCs, alerts and SPC are produced by
the same code as live data. Time is shifted with `clock.shifted_to`, so alert generation times
are the real processing times of this seed run. Back-dated alerts do not queue emails.

Storyline facts produced here:
- mostly OK production on 5 machines, 3 parts;
- 41 injected Not OK events -> NC-YYYY-00001..00041, most verified and closed, a few still open;
- on VMC-02, DC-101 C-03 (bearing bore) rises over the last 6 parts (insert wear) -> an N3 SPC
  warning is ACTIVE while every part is still in tolerance ("warned before it failed").
"""

import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models import Machine, NonConformance, User
from app.models.enums import NcStatus, ReportSource, ToleranceType
from app.schemas.ingest import ParsedReport, RawRecord
from app.seed.masters import PARTS, user_email
from app.seed.synthetic import SyntheticProcess
from app.services import audit, capa
from app.services.ingestion.pipeline import IngestRequest, ingest_parsed

logger = logging.getLogger("app.seed.history")
IST = ZoneInfo("Asia/Kolkata")

PLAN = {
    "DC-101": ["VMC-02", "VMC-02", "VMC-01"],
    "BD-205": ["CNC-T-01", "CNC-T-02"],
    "SK-310": ["HMC-01", "VMC-01"],
}
REPORTS_PER_PART_PER_DAY = 6
NOK_EVENTS = 41
LIVE_SERIAL = 457  # DC-101 SN0457 is the live demo part
DRIFT = ["72.017", "72.019", "72.021", "72.022", "72.024", "72.026"]

ROOT_CAUSES = [
    (
        "MACHINE",
        "Finish-boring insert worn",
        "Replace insert; reduce tool-life counter from 500 to 400 parts",
    ),
    (
        "MACHINE",
        "Spindle thermal growth after cold start",
        "Add 15-minute warm-up cycle before first part",
    ),
    (
        "METHOD",
        "Tool offset not updated after insert change",
        "Add offset check to insert-change checklist",
    ),
    (
        "MATERIAL",
        "Casting hardness variation in incoming batch",
        "Raise supplier hardness check; adjust feed for batch",
    ),
    (
        "MAN",
        "Wrong program revision loaded on night shift",
        "Lock program revision in DNC; brief operators",
    ),
    (
        "ENVIRONMENT",
        "Coolant temperature above limit",
        "Service chiller; add coolant temperature alarm",
    ),
    (
        "MEASUREMENT",
        "CMM stylus not re-qualified after collision",
        "Re-qualify stylus; add daily qualification check",
    ),
]
CONTAINMENT = [
    "Quarantined last {n} parts from {m}; 100% re-inspection",
    "Stopped {m}; segregated WIP since last good part ({n} parts)",
    "Held {n} parts at CMM room for re-measurement",
]


@dataclass
class Slot:
    at: datetime
    part_no: str
    machine: str
    serial: str
    index: int


def _slots(days: int, now: datetime, rng: random.Random) -> list[Slot]:
    """Report times spread over 06:30-21:30 IST each day, oldest first."""
    slots: list[Slot] = []
    counters = {p: 0 for p in PLAN}
    first_serial = {
        "DC-101": LIVE_SERIAL - days * REPORTS_PER_PART_PER_DAY,
        "BD-205": 1,
        "SK-310": 1,
    }
    today = now.astimezone(IST).date()
    for d in range(days, 0, -1):
        day = today - timedelta(days=d - 1)
        for part_no, machines in PLAN.items():
            for k in range(REPORTS_PER_PART_PER_DAY):
                minute = 390 + int((k + rng.random()) * (900 / REPORTS_PER_PART_PER_DAY))
                local = datetime(day.year, day.month, day.day, tzinfo=IST) + timedelta(
                    minutes=minute
                )
                at = local.astimezone(UTC)
                if at >= now - timedelta(minutes=10):
                    continue
                i = counters[part_no]
                counters[part_no] += 1
                slots.append(
                    Slot(
                        at,
                        part_no,
                        machines[i % len(machines)],
                        f"{first_serial[part_no] + i:04d}",
                        i,
                    )
                )
    slots.sort(key=lambda s: s.at)
    return slots


def _nok_value(spec, rng: random.Random) -> Decimal:
    over = Decimal(rng.randint(1, 9)) / 1000
    if spec.tolerance_type == ToleranceType.UPPER_ONLY or rng.random() < 0.6:
        return spec.usl + over
    return spec.lsl - over


def _lifecycle(
    session: Session, nc: NonConformance, rng: random.Random, now: datetime, leave: str | None
) -> None:
    """Drive a historical NC through acknowledge -> actions -> evidence -> submit -> verify."""
    owner = session.get(User, nc.owner_user_id)
    qhead = session.scalars(select(User).where(User.email == user_email("qhead"))).one()
    if owner is None:
        return
    o_actor = audit.Actor(owner.id, owner.role.value, "demo-seed")
    q_actor = audit.Actor(qhead.id, qhead.role.value, "demo-seed")
    t = nc.detected_at

    def at(delta: timedelta) -> datetime | None:
        nonlocal t
        t = t + delta
        return t if t < now else None

    if leave == "cancel":
        if at(timedelta(minutes=rng.randint(20, 90))):
            with clock.shifted_to(t):
                capa.cancel(session, nc, qhead, q_actor, "Re-inspection OK, probing error (demo)")
        return
    if not at(timedelta(minutes=rng.randint(3, 45))):
        return
    with clock.shifted_to(t):
        capa.acknowledge(session, nc, owner, o_actor)
    if leave == "acknowledged" or not at(timedelta(minutes=rng.randint(10, 60))):
        return
    cat, cause, action = rng.choice(ROOT_CAUSES)
    machine = session.get(Machine, nc.machine_id) if nc.machine_id else None
    with clock.shifted_to(t):
        capa.update_actions(
            session,
            nc,
            owner,
            o_actor,
            {
                "containment": rng.choice(CONTAINMENT).format(
                    n=rng.randint(4, 20), m=machine.code if machine else "machine"
                ),
                "root_cause_category": cat,
                "root_cause": cause,
                "corrective_action": action,
                "target_date": (t.astimezone(IST).date() + timedelta(days=rng.randint(2, 6))),
            },
        )
    if leave == "overdue":
        nc.target_date = (now - timedelta(days=1)).astimezone(IST).date()
        return
    if not at(timedelta(minutes=rng.randint(20, 90))):
        return
    with clock.shifted_to(t):
        capa.add_evidence(
            session,
            nc,
            owner,
            o_actor,
            f"remeasure_{nc.nc_no}.csv",
            b"char_no,actual,note\nre-measured after correction,OK,synthetic demo evidence\n",
            "Re-measurement after correction (demo)",
        )
    if not at(timedelta(hours=rng.randint(1, 20))):
        return
    with clock.shifted_to(t):
        capa.submit(session, nc, owner, o_actor)
    if leave == "pending":
        return
    if rng.random() < 0.12 and at(timedelta(hours=rng.randint(1, 8))):
        with clock.shifted_to(t):
            capa.verify(
                session, nc, qhead, q_actor, False, "Add evidence of tool-life change (demo)"
            )
        if not at(timedelta(hours=rng.randint(1, 6))):
            return
        with clock.shifted_to(t):
            capa.submit(session, nc, owner, o_actor)
    if at(timedelta(hours=rng.randint(1, 24))):
        with clock.shifted_to(t):
            capa.verify(session, nc, qhead, q_actor, True, "Verified on follow-up parts (demo)")


def seed_history(
    session: Session, days: int = 30, seed: int = 42, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    rng = random.Random(seed)
    slots = _slots(days, now, rng)
    procs = {p: SyntheticProcess(p, seed=seed + i) for i, p in enumerate(PLAN)}

    vmc02_dc101 = [s for s in slots if s.part_no == "DC-101" and s.machine == "VMC-02"]
    drift = {id(s): Decimal(v) for s, v in zip(vmc02_dc101[-len(DRIFT) :], DRIFT, strict=True)}
    protected = {id(s) for s in vmc02_dc101[-12:]}
    candidates = [s for s in slots[: int(len(slots) * 0.97)] if id(s) not in protected]
    nok_slots = {id(s) for s in rng.sample(candidates, NOK_EVENTS)}
    tail = sorted((s for s in candidates if id(s) in nok_slots), key=lambda s: s.at)[-4:]
    leave = {
        id(tail[0]): "overdue",
        id(tail[1]): "pending",
        id(tail[2]): "acknowledged",
        id(tail[3]): "pending",
    }
    cancel_ids = {
        id(s)
        for s in rng.sample(
            sorted(
                (s for s in candidates if id(s) in nok_slots and id(s) not in leave),
                key=lambda s: s.at,
            ),
            2,
        )
    }

    created_ncs = 0
    for n, s in enumerate(slots, start=1):
        values = procs[s.part_no].part(s.index, s.machine)
        if id(s) in drift:
            values["C-03"] = drift[id(s)]
        if id(s) in nok_slots:
            spec = rng.choice(PARTS[s.part_no][1])
            values[spec.char_no] = _nok_value(spec, rng)
        received = s.at + timedelta(seconds=rng.randint(40, 240))  # CMM export -> system
        parsed = ParsedReport(
            part_no=s.part_no,
            serial_no=s.serial,
            machine_code=s.machine,
            measured_at=s.at,
            operator_name="demo-inspector",
            records=[RawRecord(part_no=s.part_no, char_no=c, actual=v) for c, v in values.items()],
        )
        digest = hashlib.sha256(
            f"history:{seed}:{s.part_no}:{s.serial}:{s.at.isoformat()}".encode()
        ).hexdigest()
        req = IngestRequest(
            source=ReportSource.UPLOAD,
            received_at=received,
            actor=audit.Actor(None, "SYSTEM", "demo-seed"),
            filename=f"{s.part_no.replace('-', '')}_SN{s.serial}.csv",
        )
        with clock.history_mode(), clock.shifted_to(received):
            result = ingest_parsed(session, parsed, req, digest=digest)
        for nc_id in result.nc_ids:
            nc = session.get(NonConformance, nc_id)
            if (
                nc is not None
                and nc.status == NcStatus.OPEN
                and nc.first_report_id == result.report.id
            ):
                created_ncs += 1
                mode = "cancel" if id(s) in cancel_ids else leave.get(id(s))
                with clock.history_mode():
                    _lifecycle(session, nc, rng, now, mode)
        if n % 100 == 0:
            session.flush()
            logger.info("history: %d / %d reports", n, len(slots))
    session.flush()
    total_ncs = session.scalar(select(func.count()).select_from(NonConformance)) or 0
    return {
        "reports": len(slots),
        "ncs": int(total_ncs),
        "nok_injected": NOK_EVENTS,
        "created": created_ncs,
    }


def main(days: int = 30, seed: int = 42) -> int:
    from app.core.db import get_sessionmaker

    with get_sessionmaker().begin() as session:
        counts = seed_history(session, days=days, seed=seed)
    print(f"seeded synthetic history: {counts}")
    return 0


def today_ist() -> date:
    return datetime.now(IST).date()
