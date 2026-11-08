"""Report upload, manual entry, list and detail (Section 14)."""

import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import UPLOADERS, client_ip, get_current_user, require_roles
from app.core.db import get_db
from app.models import (
    Characteristic,
    Cmm,
    InspectionReport,
    Machine,
    Measurement,
    NcMeasurement,
    NonConformance,
    Part,
    Process,
    User,
)
from app.models.enums import ReportSource, ReportStatus, Result
from app.schemas.ingest import ManualReportIn
from app.schemas.reports import MeasurementOut, ReportDetail, ReportOut, ReportPage
from app.services.adapters.manual import parse_manual
from app.services.audit import Actor
from app.services.ingestion.pipeline import (
    DuplicateReport,
    IngestRejected,
    IngestRequest,
    IngestResult,
    ingest_file,
    ingest_parsed,
    sha256_hex,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _received_at(request: Request) -> datetime:
    return getattr(request.state, "received_at", None) or datetime.now(UTC)


def report_out(
    db: Session, report: InspectionReport, cls: type[ReportOut] = ReportOut
) -> ReportOut:
    out = cls.model_validate(report)
    if report.part_id and (part := db.get(Part, report.part_id)):
        out.part_no, out.part_name = part.part_no, part.name
    if report.machine_id and (machine := db.get(Machine, report.machine_id)):
        out.machine_code = machine.code
    if report.process_id and (process := db.get(Process, report.process_id)):
        out.process_code = process.code
    if report.cmm_id and (cmm := db.get(Cmm, report.cmm_id)):
        out.cmm_code = cmm.code
    return out


def _result_response(db: Session, result: IngestResult) -> JSONResponse:
    detail = report_detail(db, result.report)
    code = status.HTTP_201_CREATED if result.report.status != ReportStatus.FAILED else 422
    body = detail.model_dump(mode="json") | {"errors": result.errors}
    return JSONResponse(body, status_code=code)


def _duplicate_response(exc: DuplicateReport) -> JSONResponse:
    return JSONResponse(
        {
            "detail": f"This file was already ingested as {exc.report.report_no}",
            "report_id": str(exc.report.id),
            "report_no": exc.report.report_no,
        },
        status_code=status.HTTP_409_CONFLICT,
    )


@router.post("/upload", status_code=201, responses={409: {"description": "Duplicate file"}})
async def upload(
    request: Request,
    file: UploadFile = File(...),
    mapping_profile_id: uuid.UUID | None = Form(None),
    machine_id: uuid.UUID | None = Form(None),
    cmm_code: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*UPLOADERS)),
) -> JSONResponse:
    received_at = _received_at(request)
    data = await file.read()
    req = IngestRequest(
        source=ReportSource.UPLOAD,
        received_at=received_at,
        actor=Actor(user.id, user.role.value, client_ip(request)),
        filename=file.filename or "upload",
        mapping_profile_id=mapping_profile_id,
        machine_id=machine_id,
        cmm_code=cmm_code,
        file_mtime=received_at,
    )
    try:
        result = ingest_file(db, data, req)
    except IngestRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except DuplicateReport as exc:
        return _duplicate_response(exc)
    db.commit()
    return _result_response(db, result)


@router.post("/manual", status_code=201)
def manual(
    body: ManualReportIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*UPLOADERS)),
) -> JSONResponse:
    received_at = _received_at(request)
    parsed = parse_manual(body)
    digest = sha256_hex(
        f"manual:{body.model_dump_json()}:{received_at.isoformat()}:{user.id}".encode()
    )
    req = IngestRequest(
        source=ReportSource.MANUAL,
        received_at=received_at,
        actor=Actor(user.id, user.role.value, client_ip(request)),
        filename=None,
    )
    result = ingest_parsed(db, parsed, req, digest=digest)
    db.commit()
    return _result_response(db, result)


@router.get("", response_model=ReportPage)
def list_reports(
    part_id: uuid.UUID | None = None,
    machine_id: uuid.UUID | None = None,
    process_id: uuid.UUID | None = None,
    result: Result | None = None,
    report_status: ReportStatus | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    serial_no: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> ReportPage:
    q = select(InspectionReport)
    if part_id:
        q = q.where(InspectionReport.part_id == part_id)
    if machine_id:
        q = q.where(InspectionReport.machine_id == machine_id)
    if process_id:
        q = q.where(InspectionReport.process_id == process_id)
    if result:
        q = q.where(InspectionReport.part_result == result)
    if report_status:
        q = q.where(InspectionReport.status == report_status)
    if date_from:
        q = q.where(InspectionReport.measured_at >= date_from)
    if date_to:
        q = q.where(InspectionReport.measured_at < date_to)
    if serial_no:
        q = q.where(InspectionReport.serial_no == serial_no)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(InspectionReport.received_at.desc()).limit(limit).offset(offset)
    ).all()
    return ReportPage(total=total, items=[report_out(db, r) for r in rows])


def report_detail(db: Session, report: InspectionReport) -> ReportDetail:
    out = report_out(db, report, ReportDetail)
    assert isinstance(out, ReportDetail)
    rows = db.execute(
        select(Measurement, Characteristic)
        .outerjoin(Characteristic, Characteristic.id == Measurement.characteristic_id)
        .where(Measurement.report_id == report.id)
        .order_by(Measurement.char_no)
    ).all()
    out.measurements = []
    for m, c in rows:
        mo = MeasurementOut.model_validate(m)
        if c is not None:
            mo.classification = c.classification.value
            mo.tolerance_type = c.tolerance_type.value
        out.measurements.append(mo)
    ncs = db.execute(
        select(NonConformance.id, NonConformance.nc_no)
        .join(NcMeasurement, NcMeasurement.nc_id == NonConformance.id)
        .join(Measurement, Measurement.id == NcMeasurement.measurement_id)
        .where(Measurement.report_id == report.id)
        .distinct()
    ).all()
    out.nc_ids = [n.id for n in ncs]
    out.nc_nos = [n.nc_no for n in ncs]
    out.reinspected_by = list(
        db.scalars(
            select(InspectionReport.id).where(
                InspectionReport.reinspection_of_report_id == report.id
            )
        )
    )
    return out


@router.get("/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> ReportDetail:
    report = db.get(InspectionReport, report_id)
    if report is None:
        raise HTTPException(404, "report not found")
    return report_detail(db, report)
