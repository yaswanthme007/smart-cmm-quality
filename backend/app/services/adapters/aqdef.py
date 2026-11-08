"""AQDEF subset adapter (Section 8.3, SHOULD).

Q-DAS ASCII transfer format (.dfq): `K<field>[/<char index>] <value>` lines. Supported subset,
one part per file:
- K1001 part number, K1002 part description
- K2001/i characteristic number, K2002/i description, K2101/i nominal,
  K2110/i lower specification limit, K2111/i upper specification limit
- K0001/i measured value, K0004/i date/time, K0010/i machine, K0014/i part ident (serial)

Field numbers follow the Q-DAS ASCII Transfer Format manual and PC-DMIS's supported K-field
list (Section 29). This is a subset implemented from public documentation, not a certified
AQDEF interface; verify against a real export.
"""

import re
from collections import defaultdict

from app.schemas.ingest import ParsedReport, RawRecord
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig, decode_text
from app.services.ingestion.normalize import clean, to_decimal, to_mm, to_utc

_LINE = re.compile(r"^\s*K(?P<k>\d{4})(?:/(?P<i>\d+))?\s+(?P<v>.*?)\s*$")


class AqdefAdapter:
    def parse(self, data: bytes, profile: ProfileConfig, ctx: FileContext) -> ParsedReport:
        report_fields: dict[str, str] = {}
        chars: dict[int, dict[str, str]] = defaultdict(dict)
        seen_values: set[int] = set()
        for line_no, raw in enumerate(decode_text(data).splitlines(), start=1):
            if not raw.strip():
                continue
            m = _LINE.match(raw)
            if not m:
                raise AdapterError(f"line {line_no}: not a K-field line: {raw[:40]!r}")
            key, idx, value = m.group("k"), int(m.group("i") or 1), m.group("v")
            if key.startswith("1"):
                report_fields[key] = value
            elif key.startswith("2"):
                chars[idx][key] = value
            elif key.startswith("0"):
                if key == "0001":
                    if idx in seen_values:
                        raise AdapterError(
                            "file holds several parts; this AQDEF subset expects one part per file"
                        )
                    seen_values.add(idx)
                chars[idx][key] = value
        part_no = clean(report_fields.get("1001"))
        if not part_no:
            raise AdapterError("K1001 (part number) missing")
        sep = profile.decimal_separator
        unit = profile.unit
        report = ParsedReport(part_no=part_no)
        errors = []
        for idx in sorted(chars):
            c = chars[idx]
            char_no = clean(c.get("2001")) or f"C{idx}"
            if "0001" not in c:
                errors.append(f"{char_no}: K0001 (measured value) missing")
                continue
            try:
                actual = to_mm(to_decimal(c["0001"], sep), unit)
                nominal = to_mm(to_decimal(c.get("2101"), sep), unit)
                lsl = to_mm(to_decimal(c.get("2110"), sep), unit)
                usl = to_mm(to_decimal(c.get("2111"), sep), unit)
                measured_at = to_utc(c.get("0004")) if c.get("0004") else None
            except ValueError as exc:
                errors.append(f"{char_no}: {exc}")
                continue
            report.measured_at = report.measured_at or measured_at
            report.machine_code = report.machine_code or clean(c.get("0010"))
            report.serial_no = report.serial_no or clean(c.get("0014"))
            assert actual is not None
            report.records.append(
                RawRecord(
                    part_no=part_no,
                    char_no=char_no,
                    char_name=clean(c.get("2002")),
                    actual=actual,
                    nominal=nominal,
                    usl=usl,
                    lsl=lsl,
                )
            )
        if errors:
            raise AdapterError("; ".join(errors))
        if not report.records:
            raise AdapterError("no characteristics with values")
        for key in ("machine_code", "serial_no"):
            if ctx.upload_form.get(key):
                setattr(report, key, ctx.upload_form[key])
        for rec in report.records:
            rec.machine_code, rec.serial_no, rec.measured_at = (
                report.machine_code,
                report.serial_no,
                report.measured_at,
            )
        return report
