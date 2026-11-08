"""PDF report adapter (Section 8.3, COULD): deterministic pdfplumber table extraction.

Finds the first table whose header row names a characteristic column and a measured-value
column, and reads part / serial / machine from the page text. If this fails and AI is enabled,
the AI layer (app/ai/pdf_llm.py) proposes rows that a person must confirm (Section 19).
"""

import io
import re
from typing import Any

from app.schemas.ingest import ParsedReport, RawRecord
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig
from app.services.ingestion.normalize import clean, to_decimal

HEADER_ALIASES = {
    "char_no": ["char", "characteristic", "dimension", "feature", "id", "no."],
    "char_name": ["description", "name", "comment"],
    "actual": ["actual", "measured", "meas", "value"],
    "nominal": ["nominal", "nom"],
    "upper_tol": ["+tol", "upper tol", "uppertol", "tol+"],
    "lower_tol": ["-tol", "lower tol", "lowertol", "tol-"],
    "usl": ["usl", "upper limit", "max"],
    "lsl": ["lsl", "lower limit", "min"],
}
TEXT_FIELDS = {
    "part_no": r"part\s*(?:no|number)?\.?\s*[:#]?\s*([A-Z]{2}-?\d{3})",
    "serial_no": r"(?:serial|s/n|sn)\s*(?:no)?\.?\s*[:#]?\s*(\w+)",
    "machine_code": r"machine\s*[:#]?\s*([A-Z]{2,4}(?:-[A-Z])?-\d{2})",
}


def map_header(cells: list[Any]) -> dict[str, int]:
    names = [str(c or "").strip().lower() for c in cells]
    found: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for i, name in enumerate(names):
            if i in found.values():
                continue
            if name in aliases or any(name.startswith(a) for a in aliases if len(a) > 3):
                found[field] = i
                break
    return found


def parse_pdf_tables(data: bytes) -> ParsedReport:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise AdapterError("pdfplumber is not installed") from exc
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        raise AdapterError(f"not a readable PDF: {exc}") from exc
    with pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        tables = [t for page in pdf.pages for t in page.extract_tables()]
    report = ParsedReport()
    for key, pattern in TEXT_FIELDS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            setattr(report, key, m.group(1))
    for table in tables:
        if not table:
            continue
        cols = map_header(table[0])
        if "char_no" not in cols or "actual" not in cols:
            continue
        for row in table[1:]:
            try:
                values = {
                    f: to_decimal(row[i])
                    for f, i in cols.items()
                    if f not in ("char_no", "char_name")
                }
            except ValueError:
                continue
            char_no = clean(row[cols["char_no"]])
            if not char_no or values.get("actual") is None:
                continue
            report.records.append(
                RawRecord(
                    part_no=report.part_no or "",
                    char_no=char_no,
                    char_name=clean(row[cols["char_name"]]) if "char_name" in cols else None,
                    actual=values["actual"],
                    nominal=values.get("nominal"),
                    upper_tol=values.get("upper_tol"),
                    lower_tol=values.get("lower_tol"),
                    usl=values.get("usl"),
                    lsl=values.get("lsl"),
                )
            )
        if report.records:
            break
    if not report.records:
        raise AdapterError("no measurement table found in the PDF")
    return report


class PdfTableAdapter:
    def parse(self, data: bytes, profile: ProfileConfig, ctx: FileContext) -> ParsedReport:
        report = parse_pdf_tables(data)
        if ctx.upload_form.get("machine_code"):
            report.machine_code = ctx.upload_form["machine_code"]
        return report
