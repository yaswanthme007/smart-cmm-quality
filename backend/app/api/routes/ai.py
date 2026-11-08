"""Optional AI endpoints (Section 19). The deterministic core never depends on these.

- POST /ai/extract-pdf: deterministic pdfplumber first; if that fails and AI is on, Claude
  proposes rows and the report waits in NEEDS_CONFIRMATION.
- POST /reports/{id}/confirm: a person confirms / edits the rows; only then they are classified.
- GET /ncs/{id}/similar: TF-IDF suggestions from closed NCs (local, no external API).
- GET /ai/weekly-summary: templated text from KPI numbers.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai import pdf_llm, similar_nc, summary
from app.api.deps import UPLOADERS, client_ip, get_current_user, require_roles
from app.api.routes.reports import (
    _duplicate_response,
    _received_at,
    _result_response,
    report_detail,
)
from app.core import events
from app.core.db import get_db
from app.models import InspectionReport, Machine, NonConformance, User
from app.models.enums import FileKind, ReportSource, ReportStatus
from app.schemas.ingest import ParsedReport, RawRecord
from app.services import audit, settings
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig
from app.services.adapters.pdf_table import PdfTableAdapter
from app.services.ingestion.normalize import to_utc
from app.services.ingestion.pipeline import (
    DuplicateReport,
    IngestRejected,
    IngestRequest,
    check_file,
    find_duplicate,
    ingest_parsed,
    sha256_hex,
    store_file,
)
from app.services.numbering import next_number

router = APIRouter(tags=["ai"])


class ConfirmRow(BaseModel):
    char_no: str
    actual: Decimal
    char_name: str | None = None
    nominal: Decimal | None = None
    upper_tol: Decimal | None = None
    lower_tol: Decimal | None = None
    usl: Decimal | None = None
    lsl: Decimal | None = None


class ConfirmIn(BaseModel):
    part_no: str
    serial_no: str | None = None
    machine_code: str
    measured_at: datetime | None = None
    rows: list[ConfirmRow] = Field(min_length=1)


@router.post("/ai/extract-pdf", status_code=201)
async def extract_pdf(
    request: Request,
    file: UploadFile = File(...),
    machine_id: uuid.UUID | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*UPLOADERS)),
) -> JSONResponse:
    received_at = _received_at(request)
    data = await file.read()
    filename = file.filename or "report.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(415, "upload a .pdf file")
    try:
        check_file(filename, len(data))
    except IngestRejected as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    digest = sha256_hex(data)
    if (dup := find_duplicate(db, digest)) is not None:
        return _duplicate_response(DuplicateReport(dup))
    actor = audit.Actor(user.id, user.role.value, client_ip(request))
    machine = db.get(Machine, machine_id) if machine_id else None
    req = IngestRequest(
        source=ReportSource.UPLOAD,
        received_at=received_at,
        actor=actor,
        filename=filename,
        machine_id=machine_id,
    )
    storage = store_file(data, filename)

    # Step 1: deterministic table extraction -> normal pipeline.
    ctx = FileContext(
        filename=filename, upload_form={"machine_code": machine.code} if machine else {}
    )
    try:
        parsed = PdfTableAdapter().parse(
            data, ProfileConfig(name="PDF table", file_kind=FileKind.PDF), ctx
        )
    except AdapterError as deterministic_error:
        parsed = None
        reason = str(deterministic_error)
    if parsed is not None:
        result = ingest_parsed(db, parsed, req, digest=digest, storage_path=storage)
        db.commit()
        return _result_response(db, result)

    # Step 2: AI proposal, only when enabled; lands in NEEDS_CONFIRMATION.
    if not settings.ai_enabled(db):
        raise HTTPException(
            422, f"Could not read the PDF table ({reason}). AI extraction is disabled."
        )
    try:
        proposal = pdf_llm.extract_rows(data)
    except pdf_llm.AiUnavailable as exc:
        raise HTTPException(
            503, f"Could not read the PDF table ({reason}); AI extraction failed: {exc}"
        ) from exc
    if machine and not proposal.get("machine_code"):
        proposal["machine_code"] = machine.code
    report = InspectionReport(
        report_no=next_number(db, InspectionReport.report_no, "R", received_at, 6),
        received_at=received_at,
        source=ReportSource.AI_PDF,
        original_filename=filename,
        storage_path=storage,
        sha256=digest,
        status=ReportStatus.NEEDS_CONFIRMATION,
        warnings=[
            {
                "code": "PENDING_ROWS",
                "message": "AI-extracted rows: check each one against the PDF, then confirm",
                "data": proposal,
            }
        ],
        uploaded_by=user.id,
        machine_id=machine_id,
    )
    db.add(report)
    db.flush()
    audit.record(
        db,
        actor=actor,
        action="report.ai_extract",
        entity="inspection_report",
        entity_id=report.id,
        after={"report_no": report.report_no, "rows": len(proposal.get("rows", []))},
    )
    events.publish(db, "report.ingested", id=report.id, status="NEEDS_CONFIRMATION")
    db.commit()
    return JSONResponse(report_detail(db, report).model_dump(mode="json"), status_code=202)


@router.post("/reports/{report_id}/confirm")
def confirm(
    report_id: uuid.UUID,
    body: ConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*UPLOADERS)),
) -> JSONResponse:
    report = db.get(InspectionReport, report_id)
    if report is None:
        raise HTTPException(404, "report not found")
    if report.status != ReportStatus.NEEDS_CONFIRMATION:
        raise HTTPException(409, f"report is {report.status.value}, not awaiting confirmation")
    parsed = ParsedReport(
        part_no=body.part_no,
        serial_no=body.serial_no,
        machine_code=body.machine_code,
        measured_at=to_utc(body.measured_at) if body.measured_at else None,
        records=[RawRecord(part_no=body.part_no, **r.model_dump()) for r in body.rows],
    )
    actor = audit.Actor(user.id, user.role.value, client_ip(request))
    req = IngestRequest(
        source=ReportSource.AI_PDF,
        received_at=report.received_at,
        actor=actor,
        filename=report.original_filename,
    )
    try:
        result = ingest_parsed(
            db, parsed, req, digest=report.sha256, storage_path=report.storage_path, existing=report
        )
    except IngestRejected as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.message) from exc
    audit.record(
        db,
        actor=actor,
        action="report.confirm",
        entity="inspection_report",
        entity_id=report.id,
        after={"rows": len(body.rows)},
    )
    db.commit()
    return _result_response(db, result)


@router.get("/ncs/{nc_id}/similar")
def similar(
    nc_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[dict[str, Any]]:
    if not settings.ai_enabled(db):
        raise HTTPException(404, "AI suggestions are disabled")
    nc = db.get(NonConformance, nc_id)
    if nc is None:
        raise HTTPException(404, "NC not found")
    return [vars(s) for s in similar_nc.similar_ncs(db, nc)]


@router.get("/ai/weekly-summary")
def weekly(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return summary.weekly_summary(db)
