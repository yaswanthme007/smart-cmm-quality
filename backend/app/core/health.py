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


def check_worker() -> CheckStatus:
    # The worker writes settings.worker_heartbeat every 10 s once it exists (C17).
    return "not_configured"


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
