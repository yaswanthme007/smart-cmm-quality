import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.seed.masters import PARTS
from app.seed.synthetic import Effect, SyntheticProcess

GEN_DIR = Path(__file__).resolve().parents[3] / "tools" / "generator"
sys.path.insert(0, str(GEN_DIR))

import writers  # noqa: E402


def test_same_seed_gives_same_values():
    a = SyntheticProcess("DC-101", seed=7)
    b = SyntheticProcess("DC-101", seed=7)
    assert [a.part(i, "VMC-02") for i in range(5)] == [b.part(i, "VMC-02") for i in range(5)]


def test_in_control_process_stays_inside_limits():
    proc = SyntheticProcess("DC-101", seed=1)
    specs = {c.char_no: c for c in PARTS["DC-101"][1]}
    outside = 0
    for i in range(200):
        for char_no, x in proc.part(i, "VMC-01").items():
            c = specs[char_no]
            if (c.usl is not None and x > c.usl) or (c.lsl is not None and x < c.lsl):
                outside += 1
    assert outside <= 2  # Cpk 1.3-1.8 -> essentially no rejects


def test_drift_moves_values_up_on_target_machine_only():
    drift = Effect("drift", "C-03", machine="VMC-02", start=0, amount=0.002)
    proc = SyntheticProcess("DC-101", seed=3, effects=[drift])
    early = [proc.part(i, "VMC-02")["C-03"] for i in range(5)]
    late = [proc.part(i, "VMC-02")["C-03"] for i in range(30, 35)]
    assert sum(late) / 5 - sum(early) / 5 > Decimal("0.04")

    other = SyntheticProcess("DC-101", seed=3, effects=[drift])
    assert all(other.part(i, "VMC-01")["C-03"] < Decimal("72.040") for i in range(30))


def test_suspect_geometric_value_is_negative():
    proc = SyntheticProcess("DC-101", seed=3, effects=[Effect("suspect", "C-02", start=2)])
    values = [proc.part(i, "VMC-02")["C-02"] for i in range(3)]
    assert values[2] < 0
    assert all(v >= 0 for v in values[:2])


def test_writers_label_files_as_synthetic(tmp_path):
    values = SyntheticProcess("DC-101", seed=1).part(0, "VMC-02")
    at = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)
    csv_path = writers.write_csv(tmp_path, "DC-101", "0457", values, at)
    chr_path = writers.write_calypso(tmp_path, "DC-101", "0457", values, at, "VMC-02")
    dfq_path = writers.write_aqdef(tmp_path, "DC-101", "0457", values, at, "VMC-02")

    assert csv_path.name == "DC101_SN0457.csv"
    assert "SYNTHETIC DEMO DATA" in csv_path.read_text(encoding="utf-8-sig")
    assert chr_path.name == "DC101_SN0457_chr.txt"
    assert (tmp_path / "DC101_SN0457_hdr.txt").read_text().count("SYNTHETIC DEMO DATA") == 1
    assert "(demo)" in dfq_path.read_text()
    assert int(csv_path.stat().st_mtime) == int(at.timestamp())
