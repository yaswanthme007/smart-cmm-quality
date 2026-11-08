"""SPC endpoints (Section 14): streams, I-MR chart data with signals and capability, baseline."""

import itertools
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import QUALITY_HEAD_ONLY, get_actor, get_current_user, require_roles
from app.core.db import get_db
from app.models import Characteristic, Machine, Measurement, Part, SpcSignal, User
from app.models.enums import SpcSignalStatus
from app.services import audit, settings, spc

router = APIRouter(prefix="/spc", tags=["spc"])


class BaselineIn(BaseModel):
    machine_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@router.get("/streams")
def streams(
    part_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """(characteristic, machine) streams with point counts and active signals."""
    q = (
        select(
            Characteristic.id,
            Characteristic.char_no,
            Characteristic.name,
            Part.part_no,
            Machine.id.label("machine_id"),
            Machine.code,
            func.count(Measurement.id).label("n"),
        )
        .join(Measurement, Measurement.characteristic_id == Characteristic.id)
        .join(Part, Part.id == Characteristic.part_id)
        .join(Machine, Machine.id == Measurement.machine_id)
        .group_by(
            Characteristic.id,
            Characteristic.char_no,
            Characteristic.name,
            Part.part_no,
            Machine.id,
            Machine.code,
        )
        .order_by(Part.part_no, Characteristic.char_no, Machine.code)
    )
    if part_id:
        q = q.where(Characteristic.part_id == part_id)
    active = {
        (s.characteristic_id, s.machine_id): s
        for s in db.scalars(select(SpcSignal).where(SpcSignal.status == SpcSignalStatus.ACTIVE))
    }
    out = []
    for row in db.execute(q):
        signals = (
            [
                s.rule
                for s in db.scalars(
                    select(SpcSignal).where(
                        SpcSignal.characteristic_id == row.id,
                        SpcSignal.machine_id == row.machine_id,
                        SpcSignal.status == SpcSignalStatus.ACTIVE,
                    )
                )
            ]
            if (row.id, row.machine_id) in active
            else []
        )
        out.append(
            {
                "characteristic_id": str(row.id),
                "char_no": row.char_no,
                "name": row.name,
                "part_no": row.part_no,
                "machine_id": str(row.machine_id),
                "machine_code": row.code,
                "points": row.n,
                "active_signals": signals,
            }
        )
    return out


@router.get("/characteristics/{characteristic_id}")
def chart(
    characteristic_id: uuid.UUID,
    machine_id: uuid.UUID | None = None,
    limit: int = Query(200, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    char = db.get(Characteristic, characteristic_id)
    if char is None:
        raise HTTPException(404, "characteristic not found")
    part = db.get(Part, char.part_id)
    points = spc.stream_points(db, char.id, machine_id, limit=limit)
    values = [float(m.actual) for m in points]
    limits = spc.active_limits(db, char.id, machine_id)
    usl, lsl = spc.spec_limits(char)
    signals = list(
        db.scalars(
            select(SpcSignal)
            .where(SpcSignal.characteristic_id == char.id, SpcSignal.machine_id == machine_id)
            .order_by(SpcSignal.triggered_at.desc())
        )
    )
    active = [s for s in signals if s.status == SpcSignalStatus.ACTIVE]
    marks: list[dict[str, Any]] = []
    if limits is not None:
        rules = settings.spc_rules_enabled(db)
        for rule, idx in spc.rules_anywhere(
            values, float(limits.center), float(limits.sigma_within), rules
        ):
            marks.append({"rule": rule, "index": idx, "measurement_id": str(points[idx].id)})
    all_values = [float(m.actual) for m in spc.stream_points(db, char.id, machine_id)]
    cap = spc.capability(
        all_values, usl, lsl, float(limits.sigma_within) if limits else None, len(active)
    )
    mr = [None] + [abs(b - a) for a, b in itertools.pairwise(values)]
    return {
        "characteristic": {
            "id": str(char.id),
            "char_no": char.char_no,
            "name": char.name,
            "part_no": part.part_no if part else None,
            "classification": char.classification.value,
            "tolerance_type": char.tolerance_type.value,
            "nominal": float(char.nominal) if char.nominal is not None else None,
            "usl": usl,
            "lsl": lsl,
            "decimals": char.decimals,
        },
        "machine_id": str(machine_id) if machine_id else None,
        "points": [
            {
                "id": str(m.id),
                "report_id": str(m.report_id),
                "measured_at": m.measured_at.isoformat() if m.measured_at else None,
                "value": float(m.actual),
                "mr": mr[i],
                "result": m.result.value,
                "is_suspect": m.is_suspect,
            }
            for i, m in enumerate(points)
        ],
        "limits": (
            {
                "center": float(limits.center),
                "ucl": float(limits.ucl),
                "lcl": float(limits.lcl),
                "mr_bar": float(limits.mr_bar),
                "ucl_mr": spc.D4 * float(limits.mr_bar),
                "sigma_within": float(limits.sigma_within),
                "n_baseline": limits.n_baseline,
                "baseline_from": limits.baseline_from.isoformat() if limits.baseline_from else None,
                "baseline_to": limits.baseline_to.isoformat() if limits.baseline_to else None,
                "frozen_by": str(limits.frozen_by) if limits.frozen_by else None,
            }
            if limits
            else None
        ),
        "signals": [
            {
                "id": str(s.id),
                "rule": s.rule,
                "description": spc.RULE_TEXT.get(s.rule),
                "status": s.status.value,
                "triggered_at": s.triggered_at.isoformat(),
                "measurement_ids": s.measurement_ids,
            }
            for s in signals[:20]
        ],
        "marks": marks,
        "capability": {
            "valid": cap.valid,
            "message": cap.message,
            "n": cap.n,
            "cp": cap.cp,
            "cpk": cap.cpk,
            "pp": cap.pp,
            "ppk": cap.ppk,
        },
    }


@router.post("/characteristics/{characteristic_id}/baseline")
def set_baseline(
    characteristic_id: uuid.UUID,
    body: BaselineIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(*QUALITY_HEAD_ONLY)),
    actor: audit.Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Recalculate frozen control limits (Quality Head only, audited)."""
    if db.get(Characteristic, characteristic_id) is None:
        raise HTTPException(404, "characteristic not found")
    limits = spc.set_baseline(
        db,
        characteristic_id,
        body.machine_id,
        actor,
        date_from=body.date_from,
        date_to=body.date_to,
    )
    if limits is None:
        raise HTTPException(422, "need at least 2 conforming readings in the chosen range")
    db.commit()
    return {"id": str(limits.id), "n_baseline": limits.n_baseline, "center": float(limits.center)}


@router.post("/signals/{signal_id}/acknowledge")
def acknowledge_signal(
    signal_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    actor: audit.Actor = Depends(get_actor),
) -> dict[str, Any]:
    signal = db.get(SpcSignal, signal_id)
    if signal is None:
        raise HTTPException(404, "signal not found")
    if user.role.value not in ("PROCESS_OWNER", "SUPERVISOR", "QUALITY_HEAD"):
        raise HTTPException(403, "your role cannot acknowledge SPC signals")
    signal.status = SpcSignalStatus.ACKNOWLEDGED
    audit.record(
        db,
        actor=actor,
        action="spc.acknowledge",
        entity="spc_signal",
        entity_id=signal.id,
        after={"status": "ACKNOWLEDGED"},
    )
    db.commit()
    return {"id": str(signal.id), "status": signal.status.value}
