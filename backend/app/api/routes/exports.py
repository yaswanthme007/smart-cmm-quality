"""Exports: KPI workbook, NC workbook, report PDF (Section 14)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.kpi import kpi_filter
from app.api.routes.ncs import list_ncs
from app.api.routes.reports import report_detail
from app.core.db import get_db
from app.models import InspectionReport, User
from app.services import exports, kpi

router = APIRouter(prefix="/exports", tags=["exports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attachment(data: bytes, media_type: str, name: str) -> Response:
    return Response(
        data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M")


@router.get("/kpi.xlsx")
def kpi_xlsx(
    f: kpi.KpiFilter = Depends(kpi_filter),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    return _attachment(exports.kpi_workbook(db, f), XLSX, f"cmm-kpi-demo-{_stamp()}.xlsx")


@router.get("/ncs.xlsx")
def ncs_xlsx(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    page = list_ncs(
        status=None,
        bucket=None,
        severity=None,
        owner_user_id=None,
        machine_id=None,
        part_id=None,
        process_id=None,
        mine=False,
        date_from=None,
        date_to=None,
        q=None,
        limit=500,
        offset=0,
        db=db,
        user=user,
    )
    rows = [item.model_dump() for item in page.items]
    return _attachment(exports.ncs_workbook(rows), XLSX, f"cmm-ncs-demo-{_stamp()}.xlsx")


@router.get("/reports/{report_id}.pdf")
def report_pdf(
    report_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> Response:
    report = db.get(InspectionReport, report_id)
    if report is None:
        raise HTTPException(404, "report not found")
    detail = report_detail(db, report).model_dump(mode="json")
    return _attachment(exports.report_pdf(detail), "application/pdf", f"{report.report_no}.pdf")
