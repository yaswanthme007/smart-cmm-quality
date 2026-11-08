"""KPI endpoints mapped to PS-011 deliverables (Section 13). Dates are plant-local (IST) days."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import kpi

router = APIRouter(prefix="/kpi", tags=["kpi"])


def kpi_filter(
    date_from: date | None = None,
    date_to: date | None = Query(None, description="inclusive"),
    part_id: uuid.UUID | None = None,
    machine_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    shift: str | None = None,
) -> kpi.KpiFilter:
    return kpi.KpiFilter(
        date_from=kpi.parse_date(date_from),
        date_to=kpi.parse_date(date_to, end=True),
        part_id=part_id,
        machine_id=machine_id,
        process_id=process_id,
        shift=shift or None,
    )


@router.get("/summary")
def summary(
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    out = kpi.summary(db, f)
    out["ageing"] = kpi.ageing(db, f)
    return out


@router.get("/trends")
def trends(
    granularity: str = Query("day", pattern="^(day|week)$"),
    group_by: str = Query("none", pattern="^(none|machine|part|process)$"),
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return kpi.trends(db, f, granularity, group_by)


@router.get("/by")
def by_dimension(
    group_by: str = Query("machine", pattern="^(machine|part|process)$"),
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return kpi.by_dimension(db, f, group_by)


@router.get("/pareto")
def pareto(
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return kpi.pareto(db, f)


@router.get("/ageing")
def ageing(
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return kpi.ageing(db, f)


@router.get("/alert-times")
def alert_times(
    f: kpi.KpiFilter = Depends(kpi_filter),
    limit: int = Query(500, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return kpi.alert_times(db, f, limit)
