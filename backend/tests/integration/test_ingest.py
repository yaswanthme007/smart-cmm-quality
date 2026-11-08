"""Phase 4-6 acceptance: upload -> report + measurements; re-upload -> 409; mismatch warning;
Not OK -> NC, alert with generation_ms and outbox email in the same transaction."""

import io
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.routes.auth import reset_rate_limit
from app.models import (
    Alert,
    AuditLog,
    InspectionReport,
    MappingProfile,
    Measurement,
    NonConformance,
    Outbox,
)
from app.models.enums import AlertKind, NcStatus, ReportStatus
from app.seed.masters import seed_masters
from tests.helpers import login, user

GOOD = {"C-01": "48.012", "C-02": "0.015", "C-03": "72.015", "C-04": "0.020", "C-05": "110.000"}
SPEC = {
    "C-01": ("48.000", "0.025", "0.000"),
    "C-02": ("0.000", "0.040", "0.000"),
    "C-03": ("72.000", "0.030", "0.000"),
    "C-04": ("0.000", "0.050", "0.000"),
    "C-05": ("110.000", "0.050", "-0.050"),
}


def pcdmis_csv(values: dict[str, str], spec: dict | None = None, note: str = "demo") -> bytes:
    spec = spec or SPEC
    lines = ["Dimension,Description,Nominal,+Tol,-Tol,Measured,Note"]
    for char_no, actual in values.items():
        nom, up, lo = spec[char_no]
        lines.append(f"{char_no},desc {char_no},{nom},{up},{lo},{actual},{note}")
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def env(db, client):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    machines = {m["code"]: m["id"] for m in client.get("/api/machines").json()}
    profile = db.scalars(
        select(MappingProfile).where(MappingProfile.name == "PC-DMIS CSV (CMM-02)")
    ).one()
    return {"db": db, "client": client, "machines": machines, "profile_id": str(profile.id)}


def upload(env, content: bytes, name: str = "DC101_SN0457.csv", machine: str = "VMC-02"):
    return env["client"].post(
        "/api/reports/upload",
        files={"file": (name, io.BytesIO(content), "text/csv")},
        data={"machine_id": env["machines"][machine], "mapping_profile_id": env["profile_id"]},
    )


def test_ok_report_is_stored_without_nc(env):
    r = upload(env, pcdmis_csv(GOOD))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["part_no"] == "DC-101"
    assert body["serial_no"] == "0457"
    assert body["machine_code"] == "VMC-02"
    assert body["part_result"] == "OK"
    assert len(body["measurements"]) == 5
    assert body["nc_ids"] == []
    db = env["db"]
    assert db.scalar(select(func.count()).select_from(Measurement)) == 5
    assert db.scalar(select(func.count()).select_from(NonConformance)) == 0


def test_reupload_same_bytes_is_409(env):
    content = pcdmis_csv(GOOD)
    first = upload(env, content)
    second = upload(env, content)
    assert second.status_code == 409
    assert second.json()["report_id"] == first.json()["id"]
    assert env["db"].scalar(select(func.count()).select_from(InspectionReport)) == 1


def test_limit_mismatch_is_warned_but_master_limits_win(env):
    spec = dict(SPEC) | {"C-03": ("72.000", "0.040", "0.000")}  # report says +0.040
    r = upload(env, pcdmis_csv(GOOD | {"C-03": "72.035"}, spec))
    body = r.json()
    codes = [w["code"] for w in body["warnings"]]
    assert "LIMIT_MISMATCH" in codes
    c03 = next(m for m in body["measurements"] if m["char_no"] == "C-03")
    assert Decimal(c03["usl"]) == Decimal("72.030")  # master
    assert c03["result"] == "NOK"


def test_not_ok_creates_nc_alert_and_outbox_atomically(env):
    db = env["db"]
    r = upload(env, pcdmis_csv(GOOD | {"C-03": "72.034"}))
    assert r.status_code == 201
    body = r.json()
    assert body["part_result"] == "NOK"
    assert body["nok_count"] == 1
    assert len(body["nc_nos"]) == 1
    assert body["nc_nos"][0] == f"NC-{datetime.now(UTC).year}-00001"

    nc = db.scalars(select(NonConformance)).one()
    assert nc.status == NcStatus.OPEN
    assert nc.owner_user_id == user(db, "owner.vmc02").id
    assert nc.supervisor_user_id == user(db, "supervisor").id
    assert nc.severity.value == "CRITICAL"

    alert = db.scalars(select(Alert).where(Alert.kind == AlertKind.NOK)).one()
    assert alert.recipient_user_id == nc.owner_user_id
    assert alert.generation_ms is not None and alert.generation_ms < 2000
    assert (
        "C-03 Bearing bore Ø72.000 +0.030/-0.000 → measured 72.034 (+0.004 over USL)" in alert.body
    )
    assert "Severity: CRITICAL characteristic." in alert.body
    assert nc.nc_no in alert.body

    email = db.scalars(select(Outbox)).one()
    assert email.alert_id == alert.id
    assert email.payload["to"] == "owner.vmc02@demo.local"
    assert (
        db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "nc.create"))
        == 1
    )


def test_recurrence_links_to_open_nc_and_escalates_at_three(env):
    db = env["db"]
    for serial in range(1, 5):
        upload(
            env,
            pcdmis_csv(GOOD | {"C-03": "72.034"}, note=f"sn{serial}"),
            name=f"DC101_SN{serial:04d}.csv",
        )
    ncs = db.scalars(select(NonConformance)).all()
    assert len(ncs) == 1
    assert ncs[0].recurrence_count == 3
    assert ncs[0].escalation_level == 1
    kinds = [a.kind for a in db.scalars(select(Alert).order_by(Alert.created_at))]
    assert kinds.count(AlertKind.NOK) == 1
    assert kinds.count(AlertKind.RECURRENCE) == 3
    assert kinds.count(AlertKind.ESCALATION) == 1
    # every Not OK result still has a measured alert time (PS-011 / K3)
    assert all(
        a.generation_ms is not None
        for a in db.scalars(select(Alert).where(Alert.kind != AlertKind.ESCALATION))
    )


def test_marginal_does_not_push_alert(env):
    r = upload(env, pcdmis_csv(GOOD | {"C-03": "72.029"}))
    assert r.json()["part_result"] == "MARGINAL"
    assert env["db"].scalar(select(func.count()).select_from(Alert)) == 0


def test_suspect_value_flagged(env):
    r = upload(env, pcdmis_csv(GOOD | {"C-02": "-0.001"}))
    body = r.json()
    c02 = next(m for m in body["measurements"] if m["char_no"] == "C-02")
    assert c02["is_suspect"]
    assert "SUSPECT_VALUE" in [w["code"] for w in body["warnings"]]


def test_unknown_part_fails_readably_and_can_be_retried(env):
    r = upload(env, pcdmis_csv(GOOD), name="XX999_SN0001.csv")
    assert r.status_code == 422
    assert "unknown part number 'XX999'" in r.json()["errors"][0]
    assert r.json()["status"] == "FAILED"
    again = upload(env, pcdmis_csv(GOOD), name="XX999_SN0001.csv")
    assert again.status_code == 422  # FAILED files are not deduplicated


def test_bad_number_fails(env):
    r = upload(env, pcdmis_csv(GOOD | {"C-01": "4x.012"}))
    assert r.status_code == 422
    assert "not a number" in r.json()["errors"][0]


def test_wrong_extension_rejected(env):
    r = env["client"].post("/api/reports/upload", files={"file": ("x.exe", io.BytesIO(b"MZ"), "x")})
    assert r.status_code == 415


def test_sniffing_picks_profile_without_explicit_choice(env):
    r = env["client"].post(
        "/api/reports/upload",
        files={"file": ("DC101_SN0001.csv", io.BytesIO(pcdmis_csv(GOOD)), "text/csv")},
        data={"machine_id": env["machines"]["VMC-01"]},
    )
    assert r.status_code == 201, r.text


def test_german_locale_csv(env):
    text = pcdmis_csv(GOOD).decode().replace(",", ";")
    text = "\n".join(
        line if i == 0 else ";".join(c.replace(".", ",") for c in line.split(";"))
        for i, line in enumerate(text.splitlines())
    )
    r = env["client"].post(
        "/api/reports/upload",
        files={"file": ("DC101_SN0009.csv", io.BytesIO(text.encode()), "text/csv")},
        data={"machine_id": env["machines"]["HMC-01"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["part_result"] == "OK"


def test_manual_entry(env):
    r = env["client"].post(
        "/api/reports/manual",
        json={
            "part_no": "SK-310",
            "serial_no": "0100",
            "machine_code": "HMC-01",
            "rows": [
                {"char_no": "C-01", "actual": "30.025"},
                {"char_no": "C-02", "actual": "142.0"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["part_result"] == "NOK"
    nc = env["db"].scalars(select(NonConformance)).one()
    assert nc.owner_user_id == user(env["db"], "owner.hmc01").id  # machine rule wins


def test_viewer_cannot_upload(env):
    env["client"].post("/api/auth/logout")
    login(env["client"], "viewer")
    assert upload(env, pcdmis_csv(GOOD)).status_code == 403


def test_reinspection_link(env):
    first = upload(env, pcdmis_csv(GOOD | {"C-03": "72.034"}))
    second = upload(env, pcdmis_csv(GOOD | {"C-01": "48.011"}, note="re-measure"))
    assert second.json()["reinspection_of_report_id"] == first.json()["id"]
    detail = env["client"].get(f"/api/reports/{first.json()['id']}").json()
    assert detail["reinspected_by"] == [second.json()["id"]]


def test_mapping_preview_detects_columns_and_classifies(env):
    client = env["client"]
    content = pcdmis_csv(GOOD | {"C-03": "72.031"})
    detect = client.post(
        "/api/mapping-profiles/preview",
        files={"file": ("DC101_SN0001.csv", io.BytesIO(content), "text/csv")},
    ).json()
    assert detect["columns"][:3] == ["Dimension", "Description", "Nominal"]
    profile = {
        "name": "new layout",
        "file_kind": "CSV",
        "column_map": {"char_no": "Dimension", "actual": "Measured", "nominal": "Nominal"},
        "header_fields": {"part_no": {"from": "filename", "regex": r"^(?P<v>[A-Z]{2}\d{3})_"}},
    }
    preview = client.post(
        "/api/mapping-profiles/preview",
        files={"file": ("DC101_SN0001.csv", io.BytesIO(content), "text/csv")},
        data={"profile": json.dumps(profile)},
    ).json()
    assert preview["error"] is None
    results = {r["char_no"]: r["result"] for r in preview["rows"]}
    assert results["C-03"] == "NOK"
    assert results["C-01"] == "OK"
    assert (
        env["db"].scalar(select(func.count()).select_from(InspectionReport)) == 0
    )  # nothing stored


def test_failed_report_status(env):
    upload(env, b"just,garbage\n1,2\n", name="DC101_SN0002.csv")
    rep = env["db"].scalars(select(InspectionReport)).one()
    assert rep.status == ReportStatus.FAILED
