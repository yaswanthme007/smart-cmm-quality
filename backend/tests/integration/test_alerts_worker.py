"""Phase 6 acceptance: NOTIFY event for SSE, email via outbox (+ Mailpit when available),
escalation after the demo timer, alert list/read, watched folder with stability check."""

import io
import json
import socket
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import make_url, select

from app.api.routes.auth import reset_rate_limit
from app.api.routes.stream import visible_to
from app.core.config import get_settings
from app.models import Alert, InspectionReport, NonConformance, Outbox, Setting
from app.models.enums import AlertKind, OutboxStatus, ReportSource
from app.seed.masters import seed_masters
from app.services import escalation
from app.services.notifications.outbox import dispatch_batch, smtp_send
from app.worker.folder_watcher import FolderWatcher
from app.worker.main import write_heartbeat
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import login, user
from tests.integration.test_ingest import GOOD, pcdmis_csv

GEN_DIR = Path(__file__).resolve().parents[3] / "tools" / "generator"
sys.path.insert(0, str(GEN_DIR))


@pytest.fixture
def env(db, client):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    login(client, "inspector")
    machines = {m["code"]: m["id"] for m in client.get("/api/machines").json()}
    return {"db": db, "client": client, "machines": machines}


def upload_nok(env, serial="0457", value="72.034"):
    return env["client"].post(
        "/api/reports/upload",
        files={
            "file": (
                f"DC101_SN{serial}.csv",
                io.BytesIO(pcdmis_csv(GOOD | {"C-03": value}, note=serial)),
                "text/csv",
            )
        },
        data={"machine_id": env["machines"]["VMC-02"]},
    )


def test_ingest_emits_notify_events_after_commit(env):
    dsn = (
        make_url(TEST_DATABASE_URL)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("LISTEN events")
        assert upload_nok(env).status_code == 201
        events = [json.loads(n.payload) for n in conn.notifies(timeout=2, stop_after=6)]
    types = {e["type"] for e in events}
    assert {"alert.created", "nc.updated", "report.ingested", "kpi.invalidated"} <= types
    alert_event = next(e for e in events if e["type"] == "alert.created")
    owner_id = str(user(env["db"], "owner.vmc02").id)
    assert alert_event["recipient_user_id"] == owner_id
    assert visible_to(alert_event, owner_id)
    assert not visible_to(alert_event, str(user(env["db"], "supervisor").id))
    assert visible_to({"type": "kpi.invalidated"}, "anyone")


def test_outbox_dispatch_marks_sent(env):
    upload_nok(env)
    db = env["db"]
    sent = []
    assert dispatch_batch(db, sender=lambda to, subj, body: sent.append((to, subj))) == 1
    db.commit()
    row = db.scalars(select(Outbox)).one()
    assert row.status == OutboxStatus.SENT
    assert row.sent_at is not None
    assert sent[0][0] == "owner.vmc02@demo.local"
    assert sent[0][1].startswith("[NOT OK] DC-101")


def test_outbox_retries_with_backoff_when_smtp_down(env):
    upload_nok(env)
    db = env["db"]

    def down(*_):
        raise ConnectionRefusedError("smtp down")

    assert dispatch_batch(db, sender=down) == 0
    db.commit()
    row = db.scalars(select(Outbox)).one()
    assert row.status == OutboxStatus.PENDING
    assert row.attempts == 1
    assert row.next_attempt_at > datetime.now(UTC)
    assert "smtp down" in row.last_error
    assert dispatch_batch(db, sender=lambda *_: None) == 0  # not due yet


def _mailpit_up() -> bool:
    s = get_settings()
    try:
        with socket.create_connection((s.smtp_host, s.smtp_port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _mailpit_up(), reason="Mailpit/SMTP not running")
def test_email_arrives_in_mailpit(env):
    upload_nok(env, serial="0999")
    db = env["db"]
    assert dispatch_batch(db, sender=smtp_send) == 1
    db.commit()
    nc_no = db.scalars(select(NonConformance.nc_no)).one()
    with urllib.request.urlopen(
        "http://localhost:8025/api/v1/search?query=" + nc_no, timeout=5
    ) as r:
        found = json.loads(r.read())
    assert found["messages_count"] >= 1


def test_escalation_after_demo_timers(env):
    upload_nok(env)
    db = env["db"]
    nc = db.scalars(select(NonConformance)).one()
    assert escalation.sweep(db, now=nc.detected_at + timedelta(seconds=30)) == 0
    assert escalation.sweep(db, now=nc.detected_at + timedelta(seconds=61)) == 1
    db.commit()
    assert nc.escalation_level == 1
    esc = db.scalars(select(Alert).where(Alert.kind == AlertKind.ESCALATION)).one()
    assert esc.recipient_user_id == user(db, "supervisor").id
    assert escalation.sweep(db, now=nc.detected_at + timedelta(seconds=90)) == 0
    assert escalation.sweep(db, now=nc.detected_at + timedelta(seconds=121)) == 1
    db.commit()
    assert nc.escalation_level == 2
    last = db.scalars(select(Alert).where(Alert.level == 2)).one()
    assert last.recipient_user_id == user(db, "qhead").id


def test_acknowledged_nc_does_not_escalate(env):
    upload_nok(env)
    db = env["db"]
    nc = db.scalars(select(NonConformance)).one()
    env["client"].post("/api/auth/logout")
    login(env["client"], "owner.vmc02")
    assert env["client"].post(f"/api/ncs/{nc.id}/acknowledge").status_code == 200
    db.expire_all()
    assert escalation.sweep(db, now=nc.detected_at + timedelta(seconds=500)) == 0


def test_my_alerts_and_mark_read(env):
    upload_nok(env)
    client = env["client"]
    client.post("/api/auth/logout")
    login(client, "owner.vmc02")
    page = client.get("/api/alerts?mine=true").json()
    assert page["total"] == 1 and page["unread"] == 1
    alert = page["items"][0]
    assert alert["generation_ms"] is not None
    assert alert["nc_no"].startswith("NC-")
    assert client.post(f"/api/alerts/{alert['id']}/read").json()["read_at"] is not None
    assert client.get("/api/alerts").json()["unread"] == 0
    client.post("/api/auth/logout")
    login(client, "supervisor")
    assert client.get("/api/alerts").json()["total"] == 0


def test_heartbeat_makes_worker_healthy(env):
    from app.core.health import check_worker

    write_heartbeat(env["db"])
    env["db"].commit()
    assert check_worker() == "ok"
    env["db"].get(Setting, "worker_heartbeat").value = {"at": "2020-01-01T00:00:00+00:00"}
    env["db"].commit()
    assert check_worker() == "error"


def test_folder_watcher_waits_for_stable_file_then_ingests(env, tmp_path):
    import writers

    from app.seed.synthetic import SyntheticProcess

    inbox = tmp_path / "inbox" / "CMM-02"
    inbox.mkdir(parents=True)
    values = SyntheticProcess("DC-101", seed=5).part(0, "VMC-02")
    values["C-03"] = values["C-03"].__class__("72.034")
    src = writers.write_calypso(tmp_path, "DC-101", "0457", values, datetime.now(UTC), "VMC-02")
    watcher = FolderWatcher(tmp_path)

    # CALYPSO preset needs CMM-01; drop into CMM-01's inbox together with the header file.
    cmm01 = tmp_path / "inbox" / "CMM-01"
    cmm01.mkdir(parents=True)
    (tmp_path / "DC101_SN0457_hdr.txt").rename(cmm01 / "DC101_SN0457_hdr.txt")
    src.rename(cmm01 / src.name)

    watcher.scan()
    assert watcher.tick() == 0  # first check: size recorded, not yet stable
    assert watcher.tick() == 1  # unchanged across 2 checks -> ingested

    db = env["db"]
    db.expire_all()
    report = db.scalars(select(InspectionReport)).one()
    assert report.source == ReportSource.WATCH_FOLDER
    assert report.part_result.value == "NOK"
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    processed = tmp_path / "processed" / "CMM-01" / day
    assert (processed / "DC101_SN0457_chr.txt").exists()
    assert (processed / "DC101_SN0457_hdr.txt").exists()
    assert not any(cmm01.iterdir())


def test_folder_watcher_moves_bad_file_to_failed(env, tmp_path):
    inbox = tmp_path / "inbox" / "CMM-02"
    inbox.mkdir(parents=True)
    (inbox / "XX999_SN0001.csv").write_text("Dimension,Measured\nC-01,1.0\n")
    watcher = FolderWatcher(tmp_path)
    watcher.scan()
    watcher.tick()
    watcher.tick()
    failed = tmp_path / "failed" / "CMM-02"
    assert (failed / "XX999_SN0001.csv").exists()
    assert (failed / "XX999_SN0001.csv.error.txt").read_text().strip() != ""
