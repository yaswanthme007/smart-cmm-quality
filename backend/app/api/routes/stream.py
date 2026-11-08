"""Server-Sent Events (Section 6 D4): `GET /api/stream`.

Events: alert.created (only to its recipient), nc.updated, report.ingested, spc.signal,
kpi.invalidated. Payloads carry IDs; the browser refetches through REST (TanStack Query
invalidation). Auth uses the session cookie because EventSource cannot send headers.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.events import hub
from app.models import User

router = APIRouter(tags=["stream"])

HEARTBEAT_S = 15


def visible_to(event: dict, user_id: str) -> bool:
    if event.get("type") == "alert.created":
        return str(event.get("recipient_user_id")) == user_id
    return True


@router.get("/stream")
async def stream(request: Request, user: User = Depends(get_current_user)) -> StreamingResponse:
    user_id = str(user.id)

    async def events() -> AsyncIterator[str]:
        queue = hub.subscribe()
        try:
            yield "retry: 3000\n\n"
            yield f"event: hello\ndata: {json.dumps({'user_id': user_id})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if visible_to(event, user_id):
                    yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
