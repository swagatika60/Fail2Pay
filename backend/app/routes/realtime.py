"""Realtime WebSocket routes.

Exposes the live WhatsApp audit stream at ``/ws/cases/{case_id}``. Each
connected client receives JSON events whenever a new conversation message is
persisted for that case (inbound reply, outbound touchpoint, promise
reminder, etc.).
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.realtime import realtime_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/cases/{case_id}")
async def case_events(websocket: WebSocket, case_id: str):
    """Stream live conversation events for a single recovery case."""
    await realtime_manager.connect(case_id, websocket)
    try:
        while True:
            # Keep the socket alive; the server only pushes, never receives
            # meaningful frames from the dashboard. A ping lets clients detect
            # a dead connection without spamming reconnect logic.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await realtime_manager.disconnect(case_id, websocket)
    except Exception:  # noqa: BLE001
        logger.warning("realtime: websocket error for case %s", case_id)
        await realtime_manager.disconnect(case_id, websocket)
