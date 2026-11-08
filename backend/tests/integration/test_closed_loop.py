"""Section 20 integration: upload -> NC -> alert row -> outbox -> email (Mailpit when running)
-> acknowledge -> actions + evidence -> submit -> verify -> closed -> KPI values."""

import io
import json
import urllib.request

from sqlalchemy import select

from app.api.routes.auth import reset_rate_limit
from app.models import Alert, NonConformance, Outbox
from app.models.enums import AlertKind, OutboxStatus
from app.seed.masters import seed_masters
from app.services.notifications.outbox import dispatch_batch, smtp_send
from tests.helpers import login
from tests.integration.test_alerts_worker import _mailpit_up
from tests.integration.test_ingest import GOOD, pcdmis_csv


def switch(client, username):
    client.post("/api/auth/logout")
    return login(client, username)


def test_closed_loop(db, client):
    seed_masters(db)
    db.commit()
    reset_rate_limit()

    # 1. Inspector uploads a Not OK report (C-03 bearing bore 72.034, USL 72.030).
    login(client, "inspector")
    machines = {m["code"]: m["id"] for m in client.get("/api/machines").json()}
    r = client.post(
        "/api/reports/upload",
        files={
            "file": (
                "DC101_SN0457.csv",
                io.BytesIO(pcdmis_csv(GOOD | {"C-03": "72.034"}, note="loop")),
                "text/csv",
            )
        },
        data={"machine_id": machines["VMC-02"]},
    )
    assert r.status_code == 201
    nc_id = r.json()["nc_ids"][0]

    # 2. NC, alert with measured generation time, and outbox row exist together.
    alert = db.scalars(select(Alert).where(Alert.kind == AlertKind.NOK)).one()
    assert alert.generation_ms is not None
    outbox = db.scalars(select(Outbox)).one()
    assert outbox.alert_id == alert.id

    # 3. Email: real SMTP to Mailpit when it runs, otherwise a recording sender.
    sent: list[str] = []
    sender = smtp_send if _mailpit_up() else (lambda to, subject, body: sent.append(subject))
    assert dispatch_batch(db, sender=sender) == 1
    db.commit()
    db.refresh(outbox)
    assert outbox.status == OutboxStatus.SENT
    nc_no = db.get(NonConformance, nc_id).nc_no
    if _mailpit_up():
        with urllib.request.urlopen(
            f"http://localhost:8025/api/v1/search?query={nc_no}", timeout=5
        ) as resp:
            assert json.loads(resp.read())["messages_count"] >= 1
    else:
        assert sent and sent[0].startswith("[NOT OK]")

    # 4. Owner works the NC.
    switch(client, "owner.vmc02")
    assert client.post(f"/api/ncs/{nc_id}/acknowledge").json()["status"] == "ACKNOWLEDGED"
    client.patch(
        f"/api/ncs/{nc_id}",
        json={
            "containment": "Quarantined last 12 parts from VMC-02",
            "root_cause_category": "MACHINE",
            "root_cause": "Finish-boring insert worn",
            "corrective_action": "Replace insert, reduce tool-life counter from 500 to 400 parts",
            "target_date": "2026-12-31",
        },
    )
    client.post(
        f"/api/ncs/{nc_id}/evidence",
        files={"file": ("remeasure.csv", io.BytesIO(b"C-03,72.016\n"), "text/csv")},
    )
    assert client.post(f"/api/ncs/{nc_id}/submit").json()["status"] == "PENDING_VERIFICATION"

    # 5. Quality Head verifies -> closed.
    switch(client, "qhead")
    assert (
        client.post(f"/api/ncs/{nc_id}/verify", json={"approve": True, "note": "ok"}).json()[
            "status"
        ]
        == "CLOSED"
    )

    # 6. KPIs reflect the loop.
    s = client.get("/api/kpi/summary").json()
    assert s["k1"] == {"inspected": 1, "ok": 0, "ok_only": 0, "marginal": 0, "nok": 1}
    assert s["k4"]["closed"] == 1 and s["k4"]["open"] == 0
    assert s["k5"]["closed_count"] == 1 and s["k5"]["median_h"] is not None
    assert s["k3"]["count"] == 1
    assert s["k3"]["email_count"] == 1
