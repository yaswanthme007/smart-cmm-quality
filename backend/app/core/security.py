"""Password hashing (Argon2id) and session tokens (JWT in an httpOnly cookie). Section 6 D18/D19."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

SESSION_COOKIE = "cmm_session"
JWT_ALGORITHM = "HS256"

_hasher = PasswordHasher()  # argon2-cffi defaults are Argon2id with OWASP-aligned parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be set to at least 32 characters (see .env.example)")
    return secret


def create_session_token(user_id: uuid.UUID, role: str, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(hours=get_settings().jwt_expire_hours)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
