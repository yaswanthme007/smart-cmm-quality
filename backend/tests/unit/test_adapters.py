"""Golden adapter tests (Section 20): CALYPSO-style _chr.txt + _hdr.txt, AQDEF subset, generic."""

from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.models.enums import FileKind
from app.services.adapters.aqdef import AqdefAdapter
from app.services.adapters.base import AdapterError, FileContext, ProfileConfig
from app.services.adapters.calypso_chr import CalypsoChrAdapter
from app.services.adapters.generic_table import GenericTableAdapter
from app.services.adapters.registry import sniff_kind
from app.services.ingestion.normalize import to_decimal, to_mm, to_utc

FIX = Path(__file__).resolve().parents[1] / "fixtures"

CALYPSO = ProfileConfig(
    name="calypso",
    file_kind=FileKind.CALYPSO_CHR,
    delimiter="\t",
    column_map={
        "char_no": "id",
        "char_name": "comment",
        "actual": "actual",
        "nominal": "nominal",
        "upper_tol": "uppertol",
        "lower_tol": "lowertol",
    },
    header_fields={
        "part_no": {"from": "filename", "regex": r"^(?P<v>[A-Z]{2}\d{3})_"},
        "serial_no": {"from": "filename", "regex": r"_SN(?P<v>\d+)"},
        "machine_code": {"from": "column", "column": "machine"},
        "measured_at": {"from": "column", "column": "datetime"},
        "operator_name": {"from": "column", "column": "operator"},
    },
)


def test_calypso_golden_file_with_header():
    data = (FIX / "DC101_SN0457_chr.txt").read_bytes()
    ctx = FileContext(
        filename="DC101_SN0457_chr.txt",
        companions={"DC101_SN0457_hdr.txt": (FIX / "DC101_SN0457_hdr.txt").read_bytes()},
    )
    r = CalypsoChrAdapter().parse(data, CALYPSO, ctx)
    assert (r.part_no, r.serial_no, r.machine_code, r.operator_name) == (
        "DC101",
        "0457",
        "VMC-02",
        "demo-inspector",
    )
    assert r.measured_at == datetime(2026, 11, 8, 4, 45, 30, tzinfo=UTC)  # 10:15:30 IST
    assert len(r.records) == 5
    c03 = next(x for x in r.records if x.char_no == "C-03")
    assert (c03.actual, c03.nominal, c03.upper_tol, c03.lower_tol) == (
        D("72.034"),
        D("72.000"),
        D("0.030"),
        D("0.000"),
    )
    c05 = next(x for x in r.records if x.char_no == "C-05")
    assert c05.lower_tol == D("-0.050")


def test_calypso_without_header_has_no_machine():
    data = (FIX / "DC101_SN0457_chr.txt").read_bytes()
    r = CalypsoChrAdapter().parse(data, CALYPSO, FileContext(filename="DC101_SN0457_chr.txt"))
    assert r.machine_code is None
    assert r.serial_no == "0457"


def test_aqdef_golden_file_decimal_comma():
    profile = ProfileConfig(
        name="aqdef", file_kind=FileKind.AQDEF, delimiter=None, decimal_separator=","
    )
    data = (FIX / "DC101_SN0458.dfq").read_bytes()
    r = AqdefAdapter().parse(data, profile, FileContext(filename="DC101_SN0458.dfq"))
    assert (r.part_no, r.serial_no, r.machine_code) == ("DC-101", "0458", "VMC-02")
    assert r.measured_at == datetime(2026, 11, 8, 4, 50, tzinfo=UTC)
    by = {x.char_no: x for x in r.records}
    assert set(by) == {"C-01", "C-03", "C-04"}
    assert (by["C-03"].actual, by["C-03"].lsl, by["C-03"].usl) == (
        D("72.029"),
        D("72.000"),
        D("72.030"),
    )
    assert by["C-04"].lsl is None and by["C-04"].usl == D("0.050")


def test_aqdef_rejects_multiple_parts_and_garbage():
    profile = ProfileConfig(name="aqdef", file_kind=FileKind.AQDEF)
    two = b"K1001 DC-101\nK2001/1 C-01\nK0001/1 48.0\nK0001/1 48.1\n"
    with pytest.raises(AdapterError, match="several parts"):
        AqdefAdapter().parse(two, profile, FileContext(filename="x.dfq"))
    with pytest.raises(AdapterError, match="not a K-field line"):
        AqdefAdapter().parse(b"hello\n", profile, FileContext(filename="x.dfq"))


def test_generic_xlsx(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Plant sheet (demo)"])
    ws.append(["Part", "Char", "Value", "LSL", "USL"])
    ws.append(["SK-310", "C-01", 30.010, 30.0, 30.021])
    ws.append(["SK-310", "C-02", 142.2, 141.85, 142.15])
    path = tmp_path / "plant.xlsx"
    wb.save(path)
    profile = ProfileConfig(
        name="xlsx",
        file_kind=FileKind.XLSX,
        header_row=2,
        column_map={
            "part_no": "Part",
            "char_no": "Char",
            "actual": "Value",
            "lsl": "LSL",
            "usl": "USL",
        },
        header_fields={"machine_code": {"from": "const", "value": "HMC-01"}},
    )
    r = GenericTableAdapter().parse(path.read_bytes(), profile, FileContext(filename="plant.xlsx"))
    assert r.part_no == "SK-310"
    assert r.machine_code == "HMC-01"
    assert [x.actual for x in r.records] == [D("30.01"), D("142.2")]


def test_generic_header_line_and_inch_units():
    data = b"Machine: VMC-01\nDimension,Measured\nC-01,1.8900\n"
    profile = ProfileConfig(
        name="inch",
        file_kind=FileKind.CSV,
        header_row=2,
        column_map={"char_no": "Dimension", "actual": "Measured"},
        header_fields={
            "machine_code": {"from": "header_line", "regex": r"Machine: (?P<v>\S+)"},
            "part_no": {"from": "const", "value": "DC-101"},
        },
        unit="inch",
    )
    r = GenericTableAdapter().parse(data, profile, FileContext(filename="a.csv"))
    assert r.machine_code == "VMC-01"
    assert r.records[0].actual == D("48.00600")


def test_sniffing():
    assert sniff_kind("x.dfq", b"") == FileKind.AQDEF
    assert sniff_kind("x.txt", b"K1001 A\nK2001/1 B\nK0001/1 1\n") == FileKind.AQDEF
    assert sniff_kind("DC101_SN1_chr.txt", b"a\tb") == FileKind.CALYPSO_CHR
    assert sniff_kind("a.xlsx", b"") == FileKind.XLSX
    assert sniff_kind("a.csv", b"a,b") == FileKind.CSV


def test_normalize_helpers():
    assert to_decimal("1.234,5", ",") == D("1234.5")
    assert to_decimal("−0,002", ",") == D("-0.002")
    assert to_decimal("") is None
    assert to_mm(D("1"), "in") == D("25.4")
    assert to_utc("2026-11-08 10:00:00") == datetime(2026, 11, 8, 4, 30, tzinfo=UTC)
    assert to_utc("2026-11-08T10:00:00+00:00") == datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        to_decimal("abc")
