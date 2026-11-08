"""Login / logout / me. JWT lives in an httpOnly, SameSite=Strict cookie (Section 6 D18)."""

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import SESSION_COOKIE, create_session_token, verify_password
from app.models import User
from app.schemas.auth import DemoUser, LoginRequest, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Login rate limit: at most MAX_FAILURES failed attempts per IP within WINDOW_S seconds.
MAX_FAILURES = 10
WINDOW_S = 300
_failures: dict[str, deque[float]] = defaultdict(deque)


def _too_many_failures(ip: str) -> bool:
    now = time.monotonic()
    attempts = _failures[ip]
    while attempts and now - attempts[0] > WINDOW_S:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


def reset_rate_limit() -> None:
    _failures.clear()


def _start_session(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id, user.role.value),
        max_age=settings.jwt_expire_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> User:
    ip = client_ip(request) or "unknown"
    if _too_many_failures(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins, wait")

    user = db.scalars(select(User).where(func.lower(User.email) == body.email.lower())).first()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        _failures[ip].append(time.monotonic())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")

    _start_session(response, user)
    audit.record(
        db,
        actor=audit.Actor(user_id=user.id, role=user.role.value, ip=ip),
        action="auth.login",
        entity="user",
        entity_id=user.id,
    )
    db.commit()
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/demo-users", response_model=list[DemoUser])
def demo_users(db: Session = Depends(get_db)) -> list[User]:
    """Demo-user picker on the login page (only in DEMO_MODE; never returns passwords)."""
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return list(
        db.scalars(
            select(User).where(User.is_active, User.email.like("%@demo.local")).order_by(User.email)
        )
    )


class DemoLoginRequest(BaseModel):
    email: str


@router.post("/demo-login", response_model=UserOut)
def demo_login(
    body: DemoLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> User:
    """One-click login for the synthetic demo users, so nobody types a password while recording.

    Only when DEMO_MODE=true and only for `@demo.local` accounts; in plant mode the endpoint does
    not exist (404) and the normal password login is the only way in. Audited like a login.
    """
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    email = body.email.strip().lower()
    if not email.endswith("@demo.local"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "one-click login is only for demo users")
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "demo user not found")
    _start_session(response, user)
    audit.record(
        db,
        actor=audit.Actor(user_id=user.id, role=user.role.value, ip=client_ip(request)),
        action="auth.demo_login",
        entity="user",
        entity_id=user.id,
    )
    db.commit()
    return user
