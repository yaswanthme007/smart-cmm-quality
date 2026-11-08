"""Ingestion pipeline (Section 8.1): one function used by upload, watched folder and manual entry.

receive -> dedupe -> detect format -> parse -> normalize -> resolve masters -> validate ->
persist + classify + NC + alerts + outbox (one transaction) -> notify.

The caller owns the transaction: `ingest_*` flushes; the route/worker commits once, so report,
measurements, NC, alerts and the outbox email row are recorded together or not at all.
"""

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock, events
from app.core.config import get_settings
from app.models import (
    Characteristic,
    Cmm,
    InspectionReport,
    Machine,
    MappingProfile,
    Measurement,
    Part,
)
from app.models.enums import (
    FileKind,
    LimitsSource,
    ReportSource,
    ReportStatus,
    Result,
    ToleranceType,
)
from app.schemas.ingest import ParsedReport, RawRecord
from app.services import audit, settings
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig
from app.services.adapters.registry import adapter_for, sniff_kind
from app.services.classification import Limits, classify, limits_from_tolerances, worst
from app.services.ingestion.validate import limit_mismatch
from app.services.nonconformance import NokItem, raise_for_report
from app.services.numbering import next_number

logger = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".txt", ".tsv", ".dfq", ".pdf"}


class IngestRejected(Exception):
    """File refused before parsing (size, extension). Not stored."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class DuplicateReport(Exception):
    def __init__(self, report: InspectionReport) -> None:
        super().__init__(f"duplicate of report {report.report_no}")
        self.report = report


@dataclass
class IngestResult:
    report: InspectionReport
    nc_ids: list[uuid.UUID] = field(default_factory=list)
    alert_ids: list[uuid.UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class IngestRequest:
    source: ReportSource
    received_at: datetime
    actor: audit.Actor
    filename: str | None = None
    mapping_profile_id: uuid.UUID | None = None
    machine_id: uuid.UUID | None = None
    cmm_code: str | None = None
    file_mtime: datetime | None = None
    companions: dict[str, bytes] = field(default_factory=dict)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:200] or "upload"


def check_file(filename: str, size: int) -> None:
    if size > MAX_BYTES:
        raise IngestRejected(413, "file is larger than 20 MB")
    if size == 0:
        raise IngestRejected(400, "file is empty")
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise IngestRejected(
            415, f"file type not allowed; use {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )


def find_part(session: Session, part_no: str) -> Part | None:
    """Exact part number, else ignoring separators (file names often drop the hyphen: DC101)."""
    part = session.scalars(select(Part).where(Part.part_no == part_no)).first()
    if part is None:
        key = re.sub(r"[^A-Za-z0-9]", "", part_no).upper()
        part = session.scalars(
            select(Part).where(
                func.upper(func.regexp_replace(Part.part_no, "[^A-Za-z0-9]", "", "g")) == key
            )
        ).first()
    return part


def find_duplicate(session: Session, digest: str) -> InspectionReport | None:
    return session.scalars(
        select(InspectionReport).where(
            InspectionReport.sha256 == digest, InspectionReport.status != ReportStatus.FAILED
        )
    ).first()


def store_file(data: bytes, filename: str) -> str:
    """Store outside the web root under a random name; returns path relative to DATA_DIR."""
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    rel = Path("uploads") / day / f"{uuid.uuid4().hex}_{safe_filename(filename)}"
    path = get_settings().data_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(rel)


def _profiles_for(session: Session, kind: FileKind) -> list[MappingProfile]:
    return list(
        session.scalars(
            select(MappingProfile)
            .where(MappingProfile.file_kind == kind, MappingProfile.is_active)
            .order_by(MappingProfile.created_at)
        )
    )


def parse_file(
    session: Session, data: bytes, req: IngestRequest
) -> tuple[ParsedReport, MappingProfile | None]:
    """Detect format and parse. Raises AdapterError with a readable message."""
    ctx = FileContext(
        filename=req.filename or "upload",
        file_mtime=req.file_mtime,
        upload_form={},
        companions=req.companions,
    )
    if req.machine_id:
        machine = session.get(Machine, req.machine_id)
        if machine:
            ctx.upload_form["machine_code"] = machine.code

    if req.mapping_profile_id:
        profile = session.get(MappingProfile, req.mapping_profile_id)
        if profile is None:
            raise AdapterError("mapping profile not found")
        candidates = [profile]
    else:
        kind = sniff_kind(ctx.filename, data)
        candidates = []
        if req.cmm_code:
            cmm = session.scalars(select(Cmm).where(Cmm.code == req.cmm_code)).first()
            if cmm and cmm.default_mapping_profile_id:
                default = session.get(MappingProfile, cmm.default_mapping_profile_id)
                if default and default.file_kind == kind:
                    candidates.append(default)
        candidates += [p for p in _profiles_for(session, kind) if p not in candidates]
        if not candidates and kind == FileKind.PDF:
            config = ProfileConfig(name="PDF table", file_kind=FileKind.PDF)
            return adapter_for(FileKind.PDF).parse(data, config, ctx), None
        if not candidates:
            raise AdapterError(f"no active mapping profile for {kind.value} files")

    errors = []
    for profile in candidates:
        config = ProfileConfig.from_model(profile)
        try:
            return adapter_for(config.file_kind).parse(data, config, ctx), profile
        except AdapterError as exc:
            errors.append(f"{profile.name}: {exc}")
    raise AdapterError(" | ".join(errors))


def _record_failed(
    session: Session, req: IngestRequest, digest: str, storage: str | None, errors: list[str]
) -> IngestResult:
    now = clock.now()
    report = InspectionReport(
        report_no=next_number(session, InspectionReport.report_no, "R", now, 6),
        received_at=req.received_at,
        ingested_at=now,
        source=req.source,
        original_filename=req.filename,
        storage_path=storage,
        sha256=digest,
        status=ReportStatus.FAILED,
        warnings=[{"code": "FAILED", "message": e} for e in errors],
        uploaded_by=req.actor.user_id,
        machine_id=req.machine_id,
    )
    session.add(report)
    session.flush()
    audit.record(
        session,
        actor=req.actor,
        action="report.failed",
        entity="inspection_report",
        entity_id=report.id,
        after={"report_no": report.report_no, "errors": errors, "filename": req.filename},
    )
    events.publish(session, "report.ingested", id=report.id, status="FAILED")
    return IngestResult(report=report, errors=errors)


def ingest_file(session: Session, data: bytes, req: IngestRequest) -> IngestResult:
    """Full pipeline for file bytes. Raises IngestRejected / DuplicateReport."""
    check_file(req.filename or "", len(data))
    digest = sha256_hex(data)
    existing = find_duplicate(session, digest)
    if existing is not None:
        raise DuplicateReport(existing)
    storage = store_file(data, req.filename or "upload")
    try:
        parsed, profile = parse_file(session, data, req)
    except AdapterError as exc:
        return _record_failed(session, req, digest, storage, [str(exc)])
    return ingest_parsed(session, parsed, req, digest=digest, storage_path=storage, profile=profile)


def _limits_for(
    rec: RawRecord, char: Characteristic | None, guard_default: Decimal
) -> tuple[Limits | None, LimitsSource]:
    if char is not None:
        return (
            Limits(
                tolerance_type=char.tolerance_type,
                nominal=char.nominal,
                usl=char.usl,
                lsl=char.lsl,
                decimals=char.decimals,
                kind=char.kind,
                guard_band_pct=char.guard_band_pct
                if char.guard_band_pct is not None
                else guard_default,
                reference_width=char.reference_width,
                expanded_uncertainty=char.expanded_uncertainty,
            ),
            LimitsSource.MASTER,
        )
    usl, lsl = limits_from_tolerances(rec.nominal, rec.upper_tol, rec.lower_tol, rec.usl, rec.lsl)
    if usl is None and lsl is None:
        return None, LimitsSource.REPORT
    if usl is not None and lsl is not None:
        ttype = ToleranceType.BILATERAL
    else:
        ttype = ToleranceType.UPPER_ONLY if usl is not None else ToleranceType.LOWER_ONLY
    return (
        Limits(ttype, rec.nominal, usl, lsl, guard_band_pct=guard_default),
        LimitsSource.REPORT,
    )


def ingest_parsed(
    session: Session,
    parsed: ParsedReport,
    req: IngestRequest,
    *,
    digest: str,
    storage_path: str | None = None,
    profile: MappingProfile | None = None,
    existing: InspectionReport | None = None,
) -> IngestResult:
    """`existing`: a NEEDS_CONFIRMATION report (AI-extracted PDF) that confirmed rows complete."""
    errors: list[str] = []
    warnings: list[dict[str, Any]] = list(parsed.warnings)

    part = find_part(session, parsed.part_no) if parsed.part_no else None
    if part is None:
        errors.append(
            f"unknown part number {parsed.part_no!r}" if parsed.part_no else "part number missing"
        )
    machine = session.get(Machine, req.machine_id) if req.machine_id else None
    if machine is None and parsed.machine_code:
        machine = session.scalars(
            select(Machine).where(Machine.code == parsed.machine_code)
        ).first()
        if machine is None:
            errors.append(f"unknown machine {parsed.machine_code!r}")
    elif machine is None:
        errors.append("machine not identified; select the machine on upload")
    if errors and existing is not None:
        raise IngestRejected(422, "; ".join(errors))
    if errors:
        return _record_failed(session, req, digest, storage_path, errors)
    assert part is not None and machine is not None

    measured_at = parsed.measured_at
    if measured_at is None:
        measured_at = req.received_at
        warnings.append(
            {"code": "NO_MEASURED_AT", "message": "measurement time missing; used arrival time"}
        )

    chars = {
        c.char_no: c
        for c in session.scalars(select(Characteristic).where(Characteristic.part_id == part.id))
    }
    guard_default = settings.guard_band_pct_default(session)
    uncertainty_rule = settings.uncertainty_rule_enabled(session)
    cmm = (
        session.scalars(select(Cmm).where(Cmm.code == req.cmm_code)).first()
        if req.cmm_code
        else None
    )

    now = clock.now()
    previous = None
    if parsed.serial_no:
        previous = session.scalars(
            select(InspectionReport)
            .where(
                InspectionReport.part_id == part.id,
                InspectionReport.serial_no == parsed.serial_no,
                InspectionReport.status == ReportStatus.INGESTED,
            )
            .order_by(InspectionReport.received_at.desc())
        ).first()

    report = existing or InspectionReport(
        report_no=next_number(session, InspectionReport.report_no, "R", now, 6),
        sha256=digest,
        received_at=req.received_at,
        source=req.source,
        original_filename=req.filename,
        storage_path=storage_path,
        uploaded_by=req.actor.user_id,
    )
    for key, value in dict(
        cmm_id=cmm.id if cmm else None,
        part_id=part.id,
        machine_id=machine.id,
        process_id=machine.process_id,
        serial_no=parsed.serial_no,
        batch_no=parsed.batch_no,
        operator_name=parsed.operator_name,
        measured_at=measured_at,
        mapping_profile_id=profile.id if profile else None,
        status=ReportStatus.INGESTED,
        reinspection_of_report_id=previous.id if previous else None,
    ).items():
        setattr(report, key, value)
    session.add(report)
    session.flush()

    results: list[Result] = []
    measurements: list[Measurement] = []
    nok_items: list[NokItem] = []
    for rec in parsed.records:
        char = chars.get(rec.char_no)
        limits, source = _limits_for(rec, char, guard_default)
        if char is None:
            warnings.append(
                {
                    "code": "UNKNOWN_CHARACTERISTIC",
                    "char_no": rec.char_no,
                    "message": f"{rec.char_no} is not in the master for {part.part_no}; "
                    "classified with the report's own limits",
                }
            )
        if limits is None:
            errors.append(f"{rec.char_no}: unknown characteristic and no limits in the file")
            continue
        if char is not None:
            mismatch = limit_mismatch(rec, char)
            if mismatch:
                warnings.append(mismatch)
        c = classify(rec.actual, limits, uncertainty_rule=uncertainty_rule)
        if c.is_suspect:
            warnings.append(
                {
                    "code": "SUSPECT_VALUE",
                    "char_no": rec.char_no,
                    "message": f"{rec.char_no} = {c.actual}: possible probing/entry error, re-measure",
                }
            )
        m = Measurement(
            report_id=report.id,
            characteristic_id=char.id if char else None,
            char_no=rec.char_no,
            char_name=char.name if char else rec.char_name,
            machine_id=machine.id,
            measured_at=measured_at,
            actual=c.actual,
            nominal=limits.nominal,
            usl=limits.usl,
            lsl=limits.lsl,
            deviation=c.deviation,
            tolerance_used_pct=c.tolerance_used_pct,
            result=c.result,
            is_suspect=c.is_suspect,
            limits_source=source,
        )
        session.add(m)
        measurements.append(m)
        results.append(c.result)
        if c.result == Result.NOK:
            nok_items.append(NokItem(m, char, c.over_limit, limits.tolerance_type))

    if errors and existing is not None:
        for m in measurements:
            session.expunge(m)
        raise IngestRejected(422, "; ".join(errors))
    if errors:
        # Undo this attempt's rows and keep a FAILED record instead.
        for m in measurements:
            session.expunge(m)
        session.delete(report)
        session.flush()
        return _record_failed(session, req, digest, storage_path, errors)

    session.flush()
    report.part_result = worst(results)
    report.nok_count = results.count(Result.NOK)
    report.marginal_count = results.count(Result.MARGINAL)
    report.warnings = warnings

    outcome = raise_for_report(session, report, nok_items)

    from app.services import spc  # local import: SPC depends on measurements being flushed

    spc.evaluate_streams(session, measurements)

    report.ingested_at = clock.now()
    audit.record(
        session,
        actor=req.actor,
        action="report.ingest",
        entity="inspection_report",
        entity_id=report.id,
        after={
            "report_no": report.report_no,
            "part_result": report.part_result.value,
            "nok_count": report.nok_count,
            "marginal_count": report.marginal_count,
            "source": req.source.value,
            "filename": req.filename,
            "warnings": len(warnings),
        },
    )
    events.publish(session, "report.ingested", id=report.id, status="INGESTED")
    events.publish(session, "kpi.invalidated")
    session.flush()
    return IngestResult(
        report=report,
        nc_ids=[nc.id for nc in outcome.created + outcome.recurrences],
        alert_ids=outcome.alert_ids,
    )
