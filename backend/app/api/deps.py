"""Request dependencies: current user from the session cookie, and role checks (Section 14.1).

Server-side checks are mandatory; the UI only hides buttons.
"""

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import SESSION_COOKIE, decode_session_token
from app.models import User
from app.models.enums import Role
from app.services.audit import Actor


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    claims = decode_session_token(token) if token else None
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or removed")
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Dependency factory: 403 unless the current user has one of `roles`."""

    allowed = set(roles)

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot perform this action")
        return user

    return checker


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_actor(request: Request, user: User = Depends(get_current_user)) -> Actor:
    return Actor(user_id=user.id, role=user.role.value, ip=client_ip(request))


# Role groups from the permission matrix (Section 14.1).
UPLOADERS = (Role.INSPECTOR, Role.QUALITY_HEAD, Role.ADMIN)
NC_WORKERS = (Role.PROCESS_OWNER, Role.SUPERVISOR, Role.QUALITY_HEAD)
QUALITY_HEAD_ONLY = (Role.QUALITY_HEAD,)
ADMIN_ONLY = (Role.ADMIN,)
SETTINGS_EDITORS = (Role.QUALITY_HEAD, Role.ADMIN)
AUDIT_READERS = (Role.QUALITY_HEAD, Role.ADMIN)
