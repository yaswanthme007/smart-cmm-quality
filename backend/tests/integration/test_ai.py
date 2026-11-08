"""Phase 15: optional AI. Deterministic PDF first; AI rows wait for human confirmation;
app unchanged when AI is off. No external API is called in tests (extract_rows is stubbed)."""

import io

import pytest
from sqlalchemy import select

from app.ai import pdf_llm
from app.api.routes.auth import reset_rate_limit
from app.core import config
from app.models import InspectionReport, NonConformance, Setting
from app.models.enums import NcStatus
from app.seed.masters import seed_masters
from tests.helpers import login
from tests.integration.test_ingest import GOOD, pcdmis_csv


def pdf_with_table(rows, title="Part No: DC-101  Serial: 0457  Machine: VMC-02") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    table = Table([["Char", "Description", "Nominal", "LSL", "USL", "Actual"], *rows])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black")]))
    doc.build([Paragraph(title, getSampleStyleSheet()["Normal"]), table])
    return buf.getvalue()


@pytest.fixture
def env(db, client, monkeypatch):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    yield {"db": db, "client": client}
    monkeypatch.delenv("AI_ENABLED", raising=False)
    config.get_settings.cache_clear()


def enable_ai(db, monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "true")
    config.get_settings.cache_clear()
    db.merge(Setting(key="ai_enabled", value=True))
    db.commit()


def test_pdf_table_is_read_deterministically(env):
    pdf = pdf_with_table(
        [
            ["C-03", "Bearing bore", "72.000", "72.000", "72.030", "72.034"],
            ["C-01", "Pinion bore", "48.000", "48.000", "48.025", "48.010"],
        ]
    )
    r = env["client"].post(
        "/api/ai/extract-pdf",
        files={"file": ("DC101_SN0457.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["part_result"] == "NOK"
    assert body["machine_code"] == "VMC-02"
    assert len(body["nc_ids"]) == 1


def test_unreadable_pdf_without_ai_is_rejected_and_nothing_changes(env):
    pdf = pdf_with_table([], title="no table here")
    r = env["client"].post(
        "/api/ai/extract-pdf", files={"file": ("x.pdf", io.BytesIO(pdf), "application/pdf")}
    )
    assert r.status_code == 422
    assert "AI extraction is disabled" in r.json()["detail"]
    assert env["db"].scalar(select(InspectionReport.id)) is None


def test_ai_rows_wait_for_confirmation(env, monkeypatch):
    db, client = env["db"], env["client"]
    enable_ai(db, monkeypatch)
    proposal = {
        "part_no": "DC-101",
        "serial_no": "0457",
        "machine_code": "VMC-02",
        "measured_at": None,
        "rows": [
            {
                "char_no": "C-03",
                "char_name": None,
                "actual": "72.034",
                "nominal": None,
                "upper_tol": None,
                "lower_tol": None,
                "usl": None,
                "lsl": None,
            }
        ],
    }
    monkeypatch.setattr(pdf_llm, "extract_rows", lambda data: proposal)
    pdf = pdf_with_table([], title="scanned report, no table")
    r = client.post(
        "/api/ai/extract-pdf", files={"file": ("scan.pdf", io.BytesIO(pdf), "application/pdf")}
    )
    assert r.status_code == 202, r.text
    pending = r.json()
    assert pending["status"] == "NEEDS_CONFIRMATION"
    assert pending["measurements"] == []
    assert db.scalar(select(NonConformance.id)) is None  # AI never alerts

    confirm = {
        "part_no": "DC-101",
        "serial_no": "0457",
        "machine_code": "VMC-02",
        "rows": [{"char_no": "C-03", "actual": "72.034"}],
    }
    c = client.post(f"/api/reports/{pending['id']}/confirm", json=confirm)
    assert c.status_code == 201, c.text
    assert c.json()["id"] == pending["id"]
    assert c.json()["status"] == "INGESTED"
    assert c.json()["part_result"] == "NOK"
    assert client.post(f"/api/reports/{pending['id']}/confirm", json=confirm).status_code == 409


def test_similar_ncs_only_when_ai_enabled(env, monkeypatch):
    db, client = env["db"], env["client"]
    machines = {m["code"]: m["id"] for m in client.get("/api/machines").json()}
    for serial, value in [("0001", "72.034"), ("0002", "48.030")]:
        client.post(
            "/api/reports/upload",
            files={
                "file": (
                    f"DC101_SN{serial}.csv",
                    io.BytesIO(
                        pcdmis_csv(
                            GOOD | {"C-03": value}
                            if value.startswith("72")
                            else GOOD | {"C-01": value},
                            note=serial,
                        )
                    ),
                    "text/csv",
                )
            },
            data={"machine_id": machines["VMC-02"]},
        )
    ncs = db.scalars(select(NonConformance).order_by(NonConformance.nc_no)).all()
    assert client.get(f"/api/ncs/{ncs[1].id}/similar").status_code == 404
    ncs[0].status = NcStatus.CLOSED
    ncs[0].root_cause = "Finish-boring insert worn"
    ncs[0].corrective_action = "Replace insert"
    db.commit()
    enable_ai(db, monkeypatch)
    sims = client.get(f"/api/ncs/{ncs[1].id}/similar").json()
    assert sims and sims[0]["nc_no"] == ncs[0].nc_no


def test_weekly_summary_is_deterministic(env):
    text = env["client"].get("/api/ai/weekly-summary").json()["text"]
    assert "demo data" in text
    assert "parts inspected" in text
