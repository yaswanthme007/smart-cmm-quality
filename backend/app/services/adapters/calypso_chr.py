"""CALYPSO-style table file adapter (Section 8.3, SHOULD).

ZEISS CALYPSO can write tab-delimited table files into its results folder: `<name>_chr.txt`
(one characteristic per line, header row) and `<name>_hdr.txt` (report header). Column names
differ between CALYPSO versions, so this ships as a *preset mapping profile* plus this adapter,
which merges the `_hdr.txt` values into each row as extra columns (`machine`, `date`, `time`,
`datetime`, `operator`, `partnb`) for the profile's header_fields to pick from.

Implemented from public documentation and forum descriptions of the format, not vendor
certification; validate against a real file from the plant before relying on it.
"""

from typing import Any

from app.models.enums import FileKind
from app.schemas.ingest import ParsedReport
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig, decode_text
from app.services.adapters.generic_table import read_table, rows_to_report

HDR_SUFFIX = "_hdr.txt"


def parse_hdr(data: bytes) -> dict[str, str]:
    """Two tab-delimited lines: names, values. Also tolerates `key<TAB>value` per line."""
    lines = [line for line in decode_text(data).splitlines() if line.strip()]
    if len(lines) >= 2 and len(lines[0].split("\t")) == len(lines[1].split("\t")) > 2:
        return dict(zip(lines[0].split("\t"), lines[1].split("\t"), strict=True))
    out = {}
    for line in lines:
        key, _, value = line.partition("\t")
        if value:
            out[key.strip()] = value.strip()
    return out


def companion_header(ctx: FileContext) -> dict[str, str]:
    for name, data in ctx.companions.items():
        if name.lower().endswith(HDR_SUFFIX):
            return parse_hdr(data)
    return {}


class CalypsoChrAdapter:
    def parse(self, data: bytes, profile: ProfileConfig, ctx: FileContext) -> ParsedReport:
        tsv = ProfileConfig(
            name=profile.name,
            file_kind=FileKind.TSV,
            delimiter="\t",
            decimal_separator=profile.decimal_separator,
            header_row=profile.header_row or 1,
            column_map=profile.column_map,
            header_fields=profile.header_fields,
            unit=profile.unit,
        )
        columns, body, preamble = read_table(data, tsv)
        if "actual" not in [c.lower() for c in columns] and "actual" in profile.column_map.values():
            raise AdapterError("not a CALYPSO-style _chr.txt (no 'actual' column)")
        hdr = companion_header(ctx)
        if hdr:
            extra: dict[str, Any] = {
                "machine": hdr.get("machine"),
                "date": hdr.get("date"),
                "time": hdr.get("time"),
                "operator": hdr.get("operator"),
                "datetime": f"{hdr.get('date', '')} {hdr.get('time', '')}".strip() or None,
                "hdr_partnb": hdr.get("partnb"),
            }
            names = [k for k in extra if k not in columns]
            columns = columns + names
            body = [row + [extra[k] for k in names] for row in body]
        return rows_to_report(columns, body, preamble, tsv, ctx)
