"""Test helpers shared by integration tests."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.seed.masters import user_email

DEMO_PASSWORD = "test-demo-password"


def login(client: TestClient, username: str) -> TestClient:
    response = client.post(
        "/api/auth/login", json={"email": user_email(username), "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client


def user(db: Session, username: str) -> User:
    return db.scalars(select(User).where(User.email == user_email(username))).one()
