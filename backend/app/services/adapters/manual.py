"""Manual entry adapter (Section 8.3, MUST): form entry for one part, same validation as files."""

from app.schemas.ingest import ManualReportIn, ParsedReport, RawRecord
from app.services.ingestion.normalize import clean, to_utc


def parse_manual(body: ManualReportIn) -> ParsedReport:
    measured_at = to_utc(body.measured_at) if body.measured_at else None
    return ParsedReport(
        part_no=body.part_no.strip(),
        serial_no=clean(body.serial_no),
        machine_code=body.machine_code.strip(),
        measured_at=measured_at,
        operator_name=clean(body.operator_name),
        batch_no=clean(body.batch_no),
        records=[
            RawRecord(
                part_no=body.part_no.strip(),
                serial_no=clean(body.serial_no),
                machine_code=body.machine_code.strip(),
                measured_at=measured_at,
                char_no=row.char_no.strip(),
                actual=row.actual,
            )
            for row in body.rows
        ],
    )
