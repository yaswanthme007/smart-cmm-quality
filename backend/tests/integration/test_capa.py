"""Phase 7 acceptance: full corrective-action lifecycle; invalid transitions rejected."""

import io

import pytest
from sqlalchemy import select

from app.api.routes.auth import reset_rate_limit
from app.models import AuditLog, NonConformance
from app.seed.masters import seed_masters
from tests.helpers import login
from tests.integration.test_ingest import GOOD, pcdmis_csv


@pytest.fixture
def nc(db, client):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    machines = {m["code"]: m["id"] for m in client.get("/api/machines").json()}
    r = client.post(
        "/api/reports/upload",
        files={
            "file": (
                "DC101_SN0457.csv",
                io.BytesIO(pcdmis_csv(GOOD | {"C-03": "72.034"})),
                "text/csv",
            )
        },
        data={"machine_id": machines["VMC-02"]},
    )
    client.post("/api/auth/logout")
    return r.json()["nc_ids"][0]


def as_user(client, username):
    client.post("/api/auth/logout")
    login(client, username)
    return client


ACTIONS = {
    "containment": "Quarantined last 12 parts from VMC-02",
    "root_cause_category": "MACHINE",
    "root_cause": "Finish-boring insert worn",
    "corrective_action": "Replace insert, reduce tool-life counter from 500 to 400 parts",
    "target_date": "2026-11-20",
}


def test_full_lifecycle(client, db, nc):
    owner = as_user(client, "owner.vmc02")
    r = owner.post(f"/api/ncs/{nc}/acknowledge")
    assert r.status_code == 200 and r.json()["status"] == "ACKNOWLEDGED"

    r = owner.patch(f"/api/ncs/{nc}", json=ACTIONS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IN_PROGRESS"

    r = owner.post(f"/api/ncs/{nc}/submit")
    assert r.status_code == 422 and "evidence" in r.json()["detail"]

    r = owner.post(
        f"/api/ncs/{nc}/evidence",
        files={"file": ("remeasure.csv", io.BytesIO(b"C-03,72.018\n"), "text/csv")},
        data={"note": "Re-measurement after insert change (demo)"},
    )
    assert r.status_code == 201, r.text
    ev_id = r.json()["id"]
    assert owner.get(f"/api/ncs/{nc}/evidence/{ev_id}").content == b"C-03,72.018\n"

    assert owner.post(f"/api/ncs/{nc}/submit").json()["status"] == "PENDING_VERIFICATION"
    assert owner.post(f"/api/ncs/{nc}/verify", json={"approve": True}).status_code == 403

    qhead = as_user(client, "qhead")
    r = qhead.post(f"/api/ncs/{nc}/verify", json={"approve": False, "note": ""})
    assert r.status_code == 422
    r = qhead.post(
        f"/api/ncs/{nc}/verify", json={"approve": False, "note": "Add tool-life evidence"}
    )
    assert r.json()["status"] == "IN_PROGRESS"

    owner = as_user(client, "owner.vmc02")
    assert owner.post(f"/api/ncs/{nc}/submit").json()["status"] == "PENDING_VERIFICATION"
    qhead = as_user(client, "qhead")
    r = qhead.post(f"/api/ncs/{nc}/verify", json={"approve": True, "note": "Verified on 3 parts"})
    body = r.json()
    assert body["status"] == "CLOSED"
    assert body["closed_at"] is not None

    events = [e["kind"] for e in qhead.get(f"/api/ncs/{nc}/timeline").json()]
    for kind in [
        "received",
        "alert.nok",
        "nc.create",
        "nc.acknowledge",
        "nc.evidence",
        "nc.submit",
        "nc.reject",
        "nc.verify",
    ]:
        assert kind in events, kind
    alert_event = next(
        e for e in qhead.get(f"/api/ncs/{nc}/timeline").json() if e["kind"] == "alert.nok"
    )
    assert alert_event["ms"] is not None

    actions = [
        a for (a,) in db.execute(select(AuditLog.action).where(AuditLog.entity == "nonconformance"))
    ]
    assert actions.count("nc.verify") == 1


def test_invalid_transitions_rejected(client, nc):
    owner = as_user(client, "owner.vmc02")
    assert owner.patch(f"/api/ncs/{nc}", json={"containment": "x"}).status_code == 409  # not ack'd
    assert owner.post(f"/api/ncs/{nc}/submit").status_code == 409
    owner.post(f"/api/ncs/{nc}/acknowledge")
    assert owner.post(f"/api/ncs/{nc}/acknowledge").status_code == 409
    qhead = as_user(client, "qhead")
    assert qhead.post(f"/api/ncs/{nc}/verify", json={"approve": True}).status_code == 409


def test_other_owner_and_viewer_cannot_work_nc(client, nc):
    assert as_user(client, "owner.hmc01").post(f"/api/ncs/{nc}/acknowledge").status_code == 403
    assert as_user(client, "viewer").post(f"/api/ncs/{nc}/acknowledge").status_code == 403
    assert as_user(client, "inspector").post(f"/api/ncs/{nc}/acknowledge").status_code == 403
    assert as_user(client, "supervisor").post(f"/api/ncs/{nc}/acknowledge").status_code == 200


def test_cancel_requires_quality_head_and_reason(client, db, nc):
    assert (
        as_user(client, "owner.vmc02")
        .post(f"/api/ncs/{nc}/cancel", json={"reason": "x"})
        .status_code
        == 403
    )
    qhead = as_user(client, "qhead")
    assert qhead.post(f"/api/ncs/{nc}/cancel", json={"reason": " "}).status_code == 422
    r = qhead.post(f"/api/ncs/{nc}/cancel", json={"reason": "Re-inspection OK, probing error"})
    assert r.json()["status"] == "CANCELLED"
    assert qhead.post(f"/api/ncs/{nc}/acknowledge").status_code == 409


def test_reinspection_ok_shows_on_nc(client, nc):
    inspector = as_user(client, "inspector")
    machines = {m["code"]: m["id"] for m in inspector.get("/api/machines").json()}
    inspector.post(
        "/api/reports/upload",
        files={
            "file": (
                "DC101_SN0457.csv",
                io.BytesIO(pcdmis_csv(GOOD, note="re-measure")),
                "text/csv",
            )
        },
        data={"machine_id": machines["VMC-02"]},
    )
    detail = inspector.get(f"/api/ncs/{nc}").json()
    assert detail["reinspection_ok_report"]["part_result"] == "OK"


def test_nc_list_buckets_and_filters(client, db, nc):
    qhead = as_user(client, "qhead")
    assert qhead.get("/api/ncs?bucket=open").json()["total"] == 1
    assert qhead.get("/api/ncs?bucket=closed").json()["total"] == 0
    owner = as_user(client, "owner.vmc02")
    page = owner.get("/api/ncs?mine=true").json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["characteristics"] == ["C-03"]
    assert item["can_work"] is True
    assert item["machine_code"] == "VMC-02"
    nc_row = db.get(NonConformance, nc)
    assert item["nc_no"] == nc_row.nc_no


def test_evidence_type_and_state_checks(client, nc):
    owner = as_user(client, "owner.vmc02")
    r = owner.post(
        f"/api/ncs/{nc}/evidence", files={"file": ("a.png", io.BytesIO(b"x"), "image/png")}
    )
    assert r.status_code == 409  # not acknowledged yet
    owner.post(f"/api/ncs/{nc}/acknowledge")
    r = owner.post(f"/api/ncs/{nc}/evidence", files={"file": ("a.exe", io.BytesIO(b"x"), "x")})
    assert r.status_code == 415
