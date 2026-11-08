"""All REST routes under /api."""

from fastapi import APIRouter

from app.api.routes import (
    ai,
    alerts,
    audit,
    auth,
    exports,
    kpi,
    mapping,
    masters,
    ncs,
    reports,
    settings,
    spc,
    stream,
)
from app.core import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(audit.router)
api_router.include_router(masters.router)
api_router.include_router(mapping.router)
api_router.include_router(reports.router)
api_router.include_router(alerts.router)
api_router.include_router(stream.router)
api_router.include_router(ncs.router)
api_router.include_router(kpi.router)
api_router.include_router(spc.router)
api_router.include_router(settings.router)
api_router.include_router(exports.router)
api_router.include_router(ai.router)
