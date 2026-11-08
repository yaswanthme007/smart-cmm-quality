"""Phase 8 acceptance: KPI golden fixture (Section 13) and filters."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.api.routes.auth import reset_rate_limit
from app.models import NonConformance
from app.models.enums import NcStatus
from app.seed.masters import seed_masters
from app.services import kpi
from tests.helpers import login

OK = {"C-01": "48.012", "C-02": "0.015", "C-03": "72.015", "C-04": "0.020", "C-05": "110.000"}


def manual(client, serial, machine="VMC-02", **override):
    rows = [{"char_no": k, "actual": v} for k, v in (OK | override).items()]
    r = client.post(
        "/api/reports/manual",
        json={"part_no": "DC-101", "serial_no": serial, "machine_code": machine, "rows": rows},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def golden(db, client):
    """10 reports: 7 OK, 1 MARGINAL, 2 NOK (Section 13 golden fixture)."""
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    for i in range(7):
        manual(client, f"{i:04d}")
    manual(client, "0007", **{"C-03": "72.029"})  # marginal
    manual(client, "0008", **{"C-03": "72.034"})  # NOK on VMC-02
    manual(client, "0009", machine="HMC-01", **{"C-01": "48.030"})  # NOK on HMC-01
    return client


def test_kpi_golden_fixture(golden):
    s = golden.get("/api/kpi/summary").json()
    assert s["k1"] == {"inspected": 10, "ok": 8, "ok_only": 7, "marginal": 1, "nok": 2}
    assert s["k2"]["ok_pct"] == 80.0
    assert s["k2"]["nok_pct"] == 20.0
    assert s["k2"]["characteristics_measured"] == 50
    assert s["k2"]["characteristics_nok"] == 2
    assert s["k3"]["count"] == 2
    assert s["k3"]["median_ms"] is not None
    assert s["k4"] == {
        "open": 2,
        "pending": 0,
        "closed": 0,
        "cancelled": 0,
        "overdue": 0,
        "escalated_open": 0,
    }
    assert s["demo_data"] is True


def test_kpi_filters_by_machine(golden):
    machines = {m["code"]: m["id"] for m in golden.get("/api/machines").json()}
    s = golden.get(f"/api/kpi/summary?machine_id={machines['HMC-01']}").json()
    assert s["k1"]["inspected"] == 1
    assert s["k1"]["nok"] == 1
    assert s["k2"]["nok_pct"] == 100.0
    by = {row["group"]: row for row in golden.get("/api/kpi/by?group_by=machine").json()}
    assert by["VMC-02"]["inspected"] == 9 and by["VMC-02"]["nok"] == 1


def test_kpi_date_filter_excludes_other_days(golden):
    tomorrow = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    s = golden.get(f"/api/kpi/summary?date_from={tomorrow}").json()
    assert s["k1"]["inspected"] == 0
    assert s["k2"]["ok_pct"] is None


def test_trends_pareto_ageing_and_alert_times(golden):
    trend = golden.get("/api/kpi/trends?granularity=day").json()
    assert sum(t["inspected"] for t in trend) == 10
    by_machine = golden.get("/api/kpi/trends?group_by=machine").json()
    assert {t["group"] for t in by_machine} == {"VMC-02", "HMC-01"}
    pareto = golden.get("/api/kpi/pareto").json()
    assert {p["label"] for p in pareto} == {"DC-101 C-03", "DC-101 C-01"}
    assert pareto[-1]["cumulative_pct"] == 100.0
    ageing = golden.get("/api/kpi/ageing").json()
    assert ageing[0] == {"bucket": "0-1 d", "count": 2}
    times = golden.get("/api/kpi/alert-times").json()
    assert len(times) == 2 and all(t["generation_ms"] is not None for t in times)


def test_closure_lead_time(golden, db):
    nc = db.scalars(select(NonConformance).order_by(NonConformance.nc_no)).first()
    nc.status = NcStatus.CLOSED
    nc.acknowledged_at = nc.detected_at + timedelta(minutes=5)
    nc.closed_at = nc.detected_at + timedelta(hours=6)
    db.commit()
    s = golden.get("/api/kpi/summary").json()
    assert s["k4"]["closed"] == 1 and s["k4"]["open"] == 1
    assert s["k5"]["median_h"] == 6.0
    assert s["k5"]["ack_median_min"] == 5.0


def test_shift_filter(golden, db):
    s_all = kpi.summary(db, kpi.KpiFilter())
    shifts = [kpi.summary(db, kpi.KpiFilter(shift=name))["k1"]["inspected"] for name in "ABC"]
    assert sum(shifts) == s_all["k1"]["inspected"] == 10


def test_pct_rounding():
    assert kpi.pct(1, 3) == 33.3
    assert kpi.pct(2, 3) == 66.7
    assert kpi.pct(0, 0) is None
