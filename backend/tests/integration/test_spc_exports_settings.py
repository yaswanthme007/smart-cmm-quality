"""SPC signals on a drifting stream (N3 'warned before it failed'), baseline permission,
settings validation and audit, Excel/PDF exports matching the dashboard."""

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.api.routes.auth import reset_rate_limit
from app.models import Alert, AuditLog, Characteristic, Part, SpcSignal
from app.models.enums import AlertKind, SpcSignalStatus
from app.seed.masters import seed_masters
from app.seed.synthetic import SyntheticProcess
from tests.helpers import login

OK = {"C-01": "48.012", "C-02": "0.015", "C-03": "72.015", "C-04": "0.020", "C-05": "110.000"}


@pytest.fixture
def client_in(db, client):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    return client


def manual(client, serial, values):
    rows = [{"char_no": k, "actual": str(v)} for k, v in values.items()]
    r = client.post(
        "/api/reports/manual",
        json={"part_no": "DC-101", "serial_no": serial, "machine_code": "VMC-02", "rows": rows},
    )
    assert r.status_code == 201, r.text
    return r.json()


def c03_id(db):
    return db.scalars(
        select(Characteristic.id)
        .join(Part)
        .where(Part.part_no == "DC-101", Characteristic.char_no == "C-03")
    ).one()


def test_drift_raises_n3_before_parts_fail(client_in, db):
    proc = SyntheticProcess("DC-101", seed=11)
    for i in range(30):  # in-control history -> baseline from first 25
        manual(client_in, f"{i:04d}", proc.part(i, "VMC-02"))
    rising = ["72.016", "72.018", "72.020", "72.022", "72.024", "72.026"]
    for j, v in enumerate(rising):
        manual(client_in, f"{100 + j:04d}", proc.part(30 + j, "VMC-02") | {"C-03": Decimal(v)})

    signals = db.scalars(select(SpcSignal).where(SpcSignal.characteristic_id == c03_id(db))).all()
    assert "N3" in {s.rule for s in signals}
    n3 = next(s for s in signals if s.rule == "N3")
    assert n3.status == SpcSignalStatus.ACTIVE
    alerts = db.scalars(select(Alert).where(Alert.kind == AlertKind.SPC_WARNING)).all()
    assert any("N3" in a.title for a in alerts)
    # still all in tolerance: warned before it failed
    assert all(Decimal(v) <= Decimal("72.030") for v in rising)

    machines = {m["code"]: m["id"] for m in client_in.get("/api/machines").json()}
    chart = client_in.get(
        f"/api/spc/characteristics/{c03_id(db)}?machine_id={machines['VMC-02']}"
    ).json()
    assert chart["limits"]["n_baseline"] == 25
    assert len(chart["points"]) == 36
    assert any(m["rule"] == "N3" for m in chart["marks"])
    assert chart["capability"]["valid"] is False
    assert chart["capability"]["message"] == "Process not stable, capability not valid"
    streams = client_in.get("/api/spc/streams").json()
    vmc02 = next(s for s in streams if s["char_no"] == "C-03" and s["machine_code"] == "VMC-02")
    assert "N3" in vmc02["active_signals"]


def test_one_active_signal_per_rule(client_in, db):
    proc = SyntheticProcess("DC-101", seed=11)
    for i in range(25):
        manual(client_in, f"{i:04d}", proc.part(i, "VMC-02"))
    for j, v in enumerate(
        ["72.010", "72.012", "72.014", "72.016", "72.018", "72.020", "72.022", "72.024"]
    ):
        manual(client_in, f"{200 + j:04d}", proc.part(25 + j, "VMC-02") | {"C-03": Decimal(v)})
    n3 = db.scalars(select(SpcSignal).where(SpcSignal.rule == "N3")).all()
    assert len(n3) == 1


def test_baseline_is_quality_head_only_and_audited(client_in, db):
    proc = SyntheticProcess("DC-101", seed=3)
    for i in range(5):
        manual(client_in, f"{i:04d}", proc.part(i, "VMC-02"))
    machines = {m["code"]: m["id"] for m in client_in.get("/api/machines").json()}
    url = f"/api/spc/characteristics/{c03_id(db)}/baseline"
    assert client_in.post(url, json={"machine_id": machines["VMC-02"]}).status_code == 403
    client_in.post("/api/auth/logout")
    login(client_in, "qhead")
    r = client_in.post(url, json={"machine_id": machines["VMC-02"]})
    assert r.status_code == 200 and r.json()["n_baseline"] == 5
    assert db.scalars(select(AuditLog).where(AuditLog.action == "spc.baseline")).first() is not None


def test_settings_validation_permissions_and_audit(client_in, db):
    assert client_in.put("/api/settings", json={"guard_band_pct_default": 15}).status_code == 403
    client_in.post("/api/auth/logout")
    login(client_in, "qhead")
    assert client_in.put("/api/settings", json={"guard_band_pct_default": 90}).status_code == 422
    assert client_in.put("/api/settings", json={"nope": 1}).status_code == 422
    r = client_in.put("/api/settings", json={"guard_band_pct_default": 20})
    assert r.json()["guard_band_pct_default"] == 20
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "settings.update")).one()
    assert entry.before == {"value": 10} and entry.after == {"value": 20}
    # new guard band takes effect: 72.005 is now within 0.006 of LSL -> MARGINAL
    client_in.post("/api/auth/logout")
    login(client_in, "inspector")
    assert manual(client_in, "0001", OK | {"C-03": "72.005"})["part_result"] == "MARGINAL"


def test_kpi_workbook_matches_dashboard(client_in):
    for i in range(4):
        manual(client_in, f"{i:04d}", OK)
    manual(client_in, "0010", OK | {"C-03": "72.034"})
    summary = client_in.get("/api/kpi/summary").json()
    r = client_in.get("/api/exports/kpi.xlsx")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Summary"]
    assert "DEMO DATA" in ws["A1"].value
    values = {row[1]: row[2] for row in ws.iter_rows(min_row=4, values_only=True)}
    assert values["Inspected"] == summary["k1"]["inspected"] == 5
    assert values["Not OK"] == summary["k1"]["nok"] == 1
    assert values["OK %"] == summary["k2"]["ok_pct"] == 80.0
    assert values["Open actions"] == summary["k4"]["open"] == 1
    assert {"Trend by day", "Trend by machine", "Pareto", "Alert times", "NC ageing"} <= set(
        wb.sheetnames
    )


def test_nc_workbook_and_report_pdf(client_in):
    report = manual(client_in, "0457", OK | {"C-03": "72.034"})
    r = client_in.get("/api/exports/ncs.xlsx")
    ws = load_workbook(io.BytesIO(r.content)).active
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    assert len(rows) == 1 and rows[0][0].startswith("NC-")
    pdf = client_in.get(f"/api/exports/reports/{report['id']}.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
