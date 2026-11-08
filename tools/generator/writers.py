"""File writers for synthetic CMM reports. SYNTHETIC DEMO DATA ONLY.

The layouts imitate the public structure of each format (Section 3.1, 8.3); they are not
vendor-certified exports.
- generic CSV: PC-DMIS-like columns (Dimension, Description, Nominal, +Tol, -Tol, Measured).
- CALYPSO-style table file: tab-delimited `<name>_chr.txt` plus `<name>_hdr.txt` header file.
- AQDEF subset: K-field lines (`.dfq`).
"""

import csv
import io
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.models.enums import ToleranceType
from app.seed.masters import PARTS, CharSpec

DEMO_NOTE = "SYNTHETIC DEMO DATA"


def _tols(c: CharSpec) -> tuple[Decimal, Decimal]:
    """(upper_tol, lower_tol) relative to nominal; lower_tol is <= 0."""
    if c.tolerance_type == ToleranceType.UPPER_ONLY:
        return (c.usl or Decimal(0)) - c.nominal, Decimal("0.000")
    return (c.usl or c.nominal) - c.nominal, (c.lsl or c.nominal) - c.nominal


def _fmt(x: Decimal, decimal_comma: bool = False) -> str:
    s = f"{x:.3f}"
    return s.replace(".", ",") if decimal_comma else s


def base_name(part_no: str, serial: str) -> str:
    return f"{part_no.replace('-', '')}_SN{serial}"


def write_csv(
    out_dir: Path,
    part_no: str,
    serial: str,
    values: dict[str, Decimal],
    measured_at: datetime,
    decimal_comma: bool = False,
) -> Path:
    delimiter = ";" if decimal_comma else ","
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(["Dimension", "Description", "Nominal", "+Tol", "-Tol", "Measured", "Dev", "Note"])
    for c in PARTS[part_no][1]:
        up, lo = _tols(c)
        actual = values[c.char_no]
        w.writerow(
            [
                c.char_no,
                c.name,
                _fmt(c.nominal, decimal_comma),
                _fmt(up, decimal_comma),
                _fmt(lo, decimal_comma),
                _fmt(actual, decimal_comma),
                _fmt(actual - c.nominal, decimal_comma),
                DEMO_NOTE,
            ]
        )
    path = out_dir / f"{base_name(part_no, serial)}.csv"
    # BOM so Excel detects UTF-8 (the Ø in descriptions); the ingest decoder strips it.
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    ts = measured_at.timestamp()
    os.utime(path, (ts, ts))  # the PC-DMIS preset reads measured_at from file mtime
    return path


CHR_COLUMNS = [
    "planid",
    "partnb",
    "id",
    "type",
    "idsymbol",
    "actual",
    "nominal",
    "uppertol",
    "lowertol",
    "deviation",
    "exceed",
    "comment",
]


def write_calypso(
    out_dir: Path,
    part_no: str,
    serial: str,
    values: dict[str, Decimal],
    measured_at: datetime,
    machine: str,
) -> Path:
    name = base_name(part_no, serial)
    lines = ["\t".join(CHR_COLUMNS)]
    for c in PARTS[part_no][1]:
        up, lo = _tols(c)
        actual = values[c.char_no]
        if c.usl is not None and actual > c.usl:
            exceed = actual - c.usl
        elif c.lsl is not None and actual < c.lsl:
            exceed = actual - c.lsl
        else:
            exceed = Decimal(0)
        row = [
            f"{part_no}_DEMO",
            serial,
            c.char_no,
            "Diameter" if "Ø" in c.name else c.kind.value.title(),
            c.char_no,
            _fmt(actual),
            _fmt(c.nominal),
            _fmt(up),
            _fmt(lo),
            _fmt(actual - c.nominal),
            _fmt(exceed),
            c.name,
        ]
        lines.append("\t".join(row))
    hdr = [
        "\t".join(["planid", "partnb", "date", "time", "operator", "machine", "comment"]),
        "\t".join(
            [
                f"{part_no}_DEMO",
                serial,
                measured_at.strftime("%Y-%m-%d"),
                measured_at.strftime("%H:%M:%S%z"),
                "demo-inspector",
                machine,
                DEMO_NOTE,
            ]
        ),
    ]
    # Header first so a folder watcher that sees the _chr.txt also finds its _hdr.txt.
    (out_dir / f"{name}_hdr.txt").write_text("\n".join(hdr) + "\n", encoding="utf-8")
    path = out_dir / f"{name}_chr.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_aqdef(
    out_dir: Path,
    part_no: str,
    serial: str,
    values: dict[str, Decimal],
    measured_at: datetime,
    machine: str,
) -> Path:
    part_name, chars = PARTS[part_no]
    lines = [f"K0100 {len(chars)}", f"K1001 {part_no}", f"K1002 {part_name}"]
    for i, c in enumerate(chars, start=1):
        lines += [f"K2001/{i} {c.char_no}", f"K2002/{i} {c.name}", f"K2101/{i} {_fmt(c.nominal)}"]
        if c.lsl is not None:
            lines.append(f"K2110/{i} {_fmt(c.lsl)}")
        if c.usl is not None:
            lines.append(f"K2111/{i} {_fmt(c.usl)}")
    stamp = measured_at.strftime("%d.%m.%Y/%H:%M:%S")
    for i, c in enumerate(chars, start=1):
        lines += [
            f"K0001/{i} {_fmt(values[c.char_no])}",
            f"K0004/{i} {stamp}",
            f"K0010/{i} {machine}",
            f"K0014/{i} {serial}",
        ]
    path = out_dir / f"{base_name(part_no, serial)}.dfq"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
