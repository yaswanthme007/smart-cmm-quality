"""Health checks for GET /api/health: database, worker heartbeat, SMTP."""

import logging
import socket
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.db import ping_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "error", "not_configured"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: CheckStatus
    worker: CheckStatus
    smtp: CheckStatus
    demo_mode: bool


def check_db() -> CheckStatus:
    try:
        ping_db()
    except Exception:
        logger.warning("health: database unreachable", exc_info=True)
        return "error"
    return "ok"


def check_smtp() -> CheckStatus:
    settings = get_settings()
    try:
        with socket.create_connection((settings.smtp_host, settings.smtp_port), timeout=1):
            pass
    except OSError:
        return "error"
    return "ok"


HEARTBEAT_MAX_AGE_S = 30


def check_worker() -> CheckStatus:
    """The worker writes settings.worker_heartbeat every 10 s; stale after 30 s."""
    from datetime import UTC, datetime

    from app.core.db import get_sessionmaker
    from app.models import Setting

    try:
        with get_sessionmaker()() as session:
            row = session.get(Setting, "worker_heartbeat")
    except Exception:
        return "error"
    if row is None or not isinstance(row.value, dict):
        return "not_configured"
    at = datetime.fromisoformat(row.value["at"])
    return "ok" if (datetime.now(UTC) - at).total_seconds() <= HEARTBEAT_MAX_AGE_S else "error"


@router.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    db = check_db()
    result = HealthResponse(
        status="ok" if db == "ok" else "degraded",
        db=db,
        worker=check_worker(),
        smtp=check_smtp(),
        demo_mode=get_settings().demo_mode,
    )
    if db != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
