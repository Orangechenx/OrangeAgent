"""FastAPI routes for the message bus server."""

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from duckagent.bus.models import Message

from .dispatcher import resolve_recipients, should_persist
from .ws_manager import ConnectionManager

router = APIRouter()


@router.post("/api/v1/publish")
async def publish(request: Request, msg: Message) -> dict:
    """Publish a message. Non-status messages are persisted; all are dispatched."""

    db = request.app.state.db
    ws_manager: ConnectionManager = request.app.state.ws_manager

    # Persist non-status messages
    if should_persist(msg):
        await db.insert_message(msg)

    # Resolve recipients and dispatch
    recipients = resolve_recipients(msg, ws_manager.active_agent_ids)
    await ws_manager.dispatch(msg, recipients)

    return {"status": "ok", "id": msg.id}


@router.get("/api/v1/history")
async def get_history(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    from_agent: str | None = Query(None, alias="from"),
    type: str | None = Query(None),
) -> list[dict]:
    """Retrieve historical messages from persistent storage."""
    db = request.app.state.db
    messages = await db.get_history(limit=limit, from_agent=from_agent, msg_type=type)
    return [msg.model_dump(mode="json") for msg in messages]


@router.get("/api/v1/health")
async def health() -> dict:
    """Health check endpoint for readiness probes."""
    return {"status": "ok"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Single WebSocket endpoint. Query params determine role:

    - ?agent_id=<id>  → agent mode: receives messages routed to this agent
    - ?role=observer  → observer mode: receives ALL messages
    - ?role=status    → status mode: receives only status messages
    """
    ws_manager: ConnectionManager = ws.app.state.ws_manager

    agent_id = ws.query_params.get("agent_id")
    role = ws.query_params.get("role")

    if agent_id:
        await ws_manager.connect_agent(ws, agent_id)
        try:
            # Keep connection alive — messages are pushed server-side via dispatch()
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.disconnect_agent(agent_id)

    elif role == "observer":
        await ws_manager.connect_observer(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.disconnect_observer(ws)

    elif role == "status":
        await ws_manager.connect_status(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ws_manager.disconnect_status(ws)

    else:
        await ws.close(code=4000, reason="Missing agent_id or role query parameter")
