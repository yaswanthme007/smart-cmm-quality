from datetime import UTC, datetime, timedelta

import pytest

from app.api.routes.auth import reset_rate_limit
from app.core.security import SESSION_COOKIE, create_session_token, decode_session_token
from app.seed.masters import seed_masters, user_email
from tests.helpers import DEMO_PASSWORD, login, user


@pytest.fixture
def seeded(db):
    seed_masters(db)
    db.commit()
    reset_rate_limit()
    return db


def test_login_sets_httponly_strict_cookie(seeded, client):
    response = client.post(
        "/api/auth/login", json={"email": user_email("qhead"), "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "QUALITY_HEAD"
    cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "max-age=43200" in cookie  # 12 hours = one shift


def test_me_requires_login(seeded, client):
    assert client.get("/api/auth/me").status_code == 401
    login(client, "inspector")
    assert client.get("/api/auth/me").json()["email"] == user_email("inspector")


def test_wrong_password_is_401(seeded, client):
    response = client.post(
        "/api/auth/login", json={"email": user_email("qhead"), "password": "nope"}
    )
    assert response.status_code == 401


def test_login_is_rate_limited(seeded, client):
    for _ in range(10):
        client.post("/api/auth/login", json={"email": user_email("qhead"), "password": "x"})
    response = client.post(
        "/api/auth/login", json={"email": user_email("qhead"), "password": DEMO_PASSWORD}
    )
    assert response.status_code == 429


def test_logout_clears_session(seeded, client):
    login(client, "qhead")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("qhead", 200),
        ("admin", 200),
        ("inspector", 403),
        ("owner.vmc02", 403),
        ("supervisor", 403),
        ("viewer", 403),
    ],
)
def test_audit_log_permissions(seeded, client, username, expected):
    login(client, username)
    assert client.get("/api/audit").status_code == expected


def test_expired_token_is_rejected(seeded, client):
    qhead = user(seeded, "qhead")
    old = create_session_token(
        qhead.id, "QUALITY_HEAD", now=datetime.now(UTC) - timedelta(hours=13)
    )
    assert decode_session_token(old) is None
    client.cookies.set(SESSION_COOKIE, old)
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_token_is_rejected(seeded, client):
    qhead = user(seeded, "qhead")
    token = create_session_token(qhead.id, "QUALITY_HEAD")
    client.cookies.set(SESSION_COOKIE, token[:-2] + ("AA" if token[-2:] != "AA" else "BB"))
    assert client.get("/api/auth/me").status_code == 401


def test_login_is_audited(seeded, client):
    login(client, "qhead")
    entries = client.get("/api/audit", params={"action": "auth.login"}).json()
    assert entries["total"] == 1
    assert entries["items"][0]["actor_role"] == "QUALITY_HEAD"


def test_demo_user_picker_lists_users_without_secrets(seeded, client):
    users = client.get("/api/auth/demo-users").json()
    assert len(users) == 7
    assert all(set(u) == {"email", "full_name", "role"} for u in users)


def test_demo_login_one_click_only_in_demo_mode(seeded, client, monkeypatch):
    from app.core import config

    r = client.post("/api/auth/demo-login", json={"email": "owner.vmc02@demo.local"})
    assert r.status_code == 200 and r.json()["role"] == "PROCESS_OWNER"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["email"] == "owner.vmc02@demo.local"
    assert client.get("/api/audit").status_code == 403  # still a process owner, not more
    assert (
        client.post("/api/auth/demo-login", json={"email": "someone@plant.com"}).status_code == 403
    )

    monkeypatch.setenv("DEMO_MODE", "false")
    config.get_settings.cache_clear()
    try:
        assert (
            client.post("/api/auth/demo-login", json={"email": "qhead@demo.local"}).status_code
            == 404
        )
    finally:
        monkeypatch.delenv("DEMO_MODE")
        config.get_settings.cache_clear()
