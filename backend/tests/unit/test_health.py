import json
import logging

from app.core import health
from app.core.logging import JsonFormatter, request_id_var


def test_health_ok_when_db_reachable(client, monkeypatch):
    monkeypatch.setattr(health, "ping_db", lambda: None)
    monkeypatch.setattr(health, "check_smtp", lambda: "ok")

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["smtp"] == "ok"
    assert body["worker"] == "not_configured"


def test_health_503_when_db_down(client, monkeypatch):
    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(health, "ping_db", boom)
    monkeypatch.setattr(health, "check_smtp", lambda: "error")

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["db"] == "error"


def test_request_id_is_echoed_or_generated(client, monkeypatch):
    monkeypatch.setattr(health, "ping_db", lambda: None)
    monkeypatch.setattr(health, "check_smtp", lambda: "ok")

    echoed = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    generated = client.get("/api/health")

    assert echoed.headers["X-Request-ID"] == "abc123"
    assert len(generated.headers["X-Request-ID"]) == 32


def test_openapi_docs_served_under_api(client):
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_json_log_includes_request_id():
    token = request_id_var.set("req-1")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert entry["msg"] == "hello"
    assert entry["request_id"] == "req-1"
    assert entry["level"] == "INFO"
