"""Generic table adapter for CSV / TSV / XLSX (Section 8.3, MUST).

Driven entirely by the mapping profile: `column_map` maps canonical fields to source columns,
`header_fields` says where part no / serial / machine / measured_at come from. This covers
PC-DMIS CSV/XLSX exports and plant Excel sheets.
"""

import csv
import io
import re
from typing import Any

from app.models.enums import FileKind
from app.schemas.ingest import ParsedReport, RawRecord
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig, decode_text
from app.services.ingestion.normalize import clean, to_decimal, to_mm, to_utc

CANONICAL_FIELDS = [
    "char_no",
    "char_name",
    "actual",
    "nominal",
    "upper_tol",
    "lower_tol",
    "usl",
    "lsl",
    "part_no",
    "serial_no",
    "machine_code",
    "measured_at",
]
REQUIRED_COLUMNS = ["char_no", "actual"]
NUMERIC_FIELDS = ["actual", "nominal", "upper_tol", "lower_tol", "usl", "lsl"]
HEADER_KEYS = ["part_no", "serial_no", "machine_code", "measured_at", "operator_name", "batch_no"]


def read_table(data: bytes, profile: ProfileConfig) -> tuple[list[str], list[list[Any]], list[str]]:
    """Return (columns, data rows, lines above the header) for the profile's file kind."""
    header_row = max(profile.header_row, 1)
    if profile.file_kind == FileKind.XLSX:
        rows = _xlsx_rows(data)
    else:
        text = decode_text(data)
        delimiter = "\t" if profile.file_kind == FileKind.TSV else (profile.delimiter or ",")
        if delimiter == "\\t":
            delimiter = "\t"
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if len(rows) < header_row:
        raise AdapterError(f"file has no header row {header_row}")
    preamble = [" ".join(str(c) for c in r if c not in (None, "")) for r in rows[: header_row - 1]]
    columns = [clean(c) or f"column_{i + 1}" for i, c in enumerate(rows[header_row - 1])]
    body = [r for r in rows[header_row:] if any(c not in (None, "") for c in r)]
    return columns, body, preamble


def _xlsx_rows(data: bytes) -> list[list[Any]]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several types for bad files
        raise AdapterError(f"not a readable .xlsx workbook: {exc}") from exc
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def resolve_header_fields(
    profile: ProfileConfig,
    ctx: FileContext,
    first_row: dict[str, Any] | None,
    preamble: list[str],
) -> dict[str, Any]:
    """Resolve report-level fields from filename / column / form / mtime / header line / const."""
    out: dict[str, Any] = {}
    for key, rule in profile.header_fields.items():
        source = rule.get("from")
        value: Any = None
        if source == "filename":
            m = re.search(rule.get("regex", ""), ctx.filename)
            value = (m.groupdict().get("v") or m.group(0)) if m else None
        elif source == "column" and first_row is not None:
            value = first_row.get(rule.get("column", ""))
        elif source == "upload_form":
            value = ctx.upload_form.get(key)
        elif source == "file_mtime":
            value = ctx.file_mtime
        elif source == "header_line":
            for line in preamble:
                m = re.search(rule.get("regex", ""), line)
                if m:
                    value = m.groupdict().get("v") or m.group(0)
                    break
        elif source == "const":
            value = rule.get("value")
        if value not in (None, ""):
            out[key] = value
    # The upload form always wins for machine when the user picked one explicitly.
    for key in ("machine_code", "serial_no"):
        if ctx.upload_form.get(key):
            out[key] = ctx.upload_form[key]
    return out


def rows_to_report(
    columns: list[str],
    body: list[list[Any]],
    preamble: list[str],
    profile: ProfileConfig,
    ctx: FileContext,
) -> ParsedReport:
    cmap = {k: v for k, v in profile.column_map.items() if v and not k.startswith("_")}
    missing = [f for f in REQUIRED_COLUMNS if f not in cmap]
    if missing:
        raise AdapterError(f"mapping profile has no column for: {', '.join(missing)}")
    absent = [v for v in cmap.values() if v not in columns]
    if absent:
        raise AdapterError(
            f"columns not found in file: {', '.join(absent)} (file has: {', '.join(columns)})"
        )

    index = {name: i for i, name in enumerate(columns)}
    dicts = [{c: (r[i] if i < len(r) else None) for c, i in index.items()} for r in body]
    header = resolve_header_fields(profile, ctx, dicts[0] if dicts else None, preamble)

    report = ParsedReport()
    for key in HEADER_KEYS:
        if key in header:
            value = header[key]
            setattr(report, key, to_utc(value) if key == "measured_at" else clean(value))

    errors: list[str] = []
    for line_no, row in enumerate(dicts, start=profile.header_row + 1):
        values: dict[str, Any] = {}
        try:
            for f in NUMERIC_FIELDS:
                if f in cmap:
                    values[f] = to_mm(
                        to_decimal(row[cmap[f]], profile.decimal_separator), profile.unit
                    )
        except ValueError as exc:
            errors.append(f"row {line_no}: {exc}")
            continue
        char_no = clean(row[cmap["char_no"]])
        if not char_no:
            errors.append(f"row {line_no}: characteristic number is empty")
            continue
        if values.get("actual") is None:
            errors.append(f"row {line_no} ({char_no}): measured value is empty")
            continue
        lower_tol = values.get("lower_tol")
        if (
            lower_tol is not None
            and lower_tol > 0
            and profile.column_map.get("_lower_tol_sign") == "magnitude"
        ):
            lower_tol = -lower_tol
        report.records.append(
            RawRecord(
                part_no=clean(row.get(cmap.get("part_no", ""))) or report.part_no or "",
                serial_no=report.serial_no,
                machine_code=report.machine_code,
                measured_at=report.measured_at,
                char_no=char_no,
                char_name=clean(row.get(cmap["char_name"])) if "char_name" in cmap else None,
                actual=values["actual"],
                nominal=values.get("nominal"),
                upper_tol=values.get("upper_tol"),
                lower_tol=lower_tol,
                usl=values.get("usl"),
                lsl=values.get("lsl"),
                unit="mm",
            )
        )
    if errors:
        raise AdapterError("; ".join(errors[:10]))
    if not report.records:
        raise AdapterError("no characteristic rows found")
    if not report.part_no and report.records[0].part_no:
        report.part_no = report.records[0].part_no
    return report


class GenericTableAdapter:
    def parse(self, data: bytes, profile: ProfileConfig, ctx: FileContext) -> ParsedReport:
        columns, body, preamble = read_table(data, profile)
        return rows_to_report(columns, body, preamble, profile, ctx)
