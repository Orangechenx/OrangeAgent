"""FastAPI routes for the message bus server."""

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from orangeagent.bus.models import Message
from orangeagent.runtime.models import HandoffRecord, MemoryRecord, RunStepRecord, ToolCallRecord

from .dispatcher import resolve_recipients, should_persist
from .ws_manager import ConnectionManager

router = APIRouter()


@router.post("/api/v1/publish")
async def publish(request: Request, msg: Message) -> dict:
    """Publish a message. Non-status messages are persisted; all are dispatched."""

    db = request.app.state.db
    ws_manager: ConnectionManager = request.app.state.ws_manager

    msg = await db.prepare_message(msg)

    # Persist non-status messages
    if should_persist(msg):
        await db.persist_message_with_runtime(msg)

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


@router.get("/api/v1/tasks")
async def get_tasks(
    request: Request,
    session_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    tasks = await db.get_tasks(session_id=session_id, limit=limit)
    return [task.model_dump(mode="json") for task in tasks]


@router.get("/api/v1/runs")
async def get_runs(
    request: Request,
    session_id: str | None = Query(None),
    task_id: str | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    runs = await db.get_runs(
        session_id=session_id,
        task_id=task_id,
        run_id=run_id,
        limit=limit,
    )
    return [run.model_dump(mode="json") for run in runs]


@router.get("/api/v1/evidence")
async def get_evidence(
    request: Request,
    task_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    evidence = await db.get_evidence(task_id=task_id, limit=limit)
    return [item.model_dump(mode="json") for item in evidence]


@router.get("/api/v1/memories")
async def get_memories(
    request: Request,
    session_id: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    memories = await db.get_memories(session_id=session_id, task_id=task_id, limit=limit)
    return [memory.model_dump(mode="json") for memory in memories]


@router.post("/api/v1/memories")
async def add_memory(request: Request, memory: MemoryRecord) -> dict:
    db = request.app.state.db
    saved = await db.add_memory(memory)
    return saved.model_dump(mode="json")


@router.get("/api/v1/context")
async def build_context(
    request: Request,
    session_id: str = Query(...),
    task_id: str | None = Query(None),
    query: str = Query(""),
) -> dict:
    db = request.app.state.db
    context = await db.build_context(session_id=session_id, task_id=task_id, query=query)
    return {"context": context}


@router.get("/api/v1/system-context")
async def build_system_context(
    request: Request,
    limit: int = Query(15, ge=1, le=50),
) -> dict:
    db = request.app.state.db
    context = await db.build_system_context(limit=limit)
    return {"context": context}


@router.get("/api/v1/tool-calls")
async def get_tool_calls(
    request: Request,
    task_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    records = await db.get_tool_calls(task_id=task_id, limit=limit)
    return [record.model_dump(mode="json") for record in records]


@router.post("/api/v1/tool-calls")
async def add_tool_call(request: Request, record: ToolCallRecord) -> dict:
    db = request.app.state.db
    saved = await db.add_tool_call(record)
    return saved.model_dump(mode="json")


@router.get("/api/v1/handoffs")
async def get_handoffs(
    request: Request,
    task_id: str | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    db = request.app.state.db
    records = await db.get_handoffs(task_id=task_id, run_id=run_id, limit=limit)
    return [record.model_dump(mode="json") for record in records]


@router.post("/api/v1/handoffs")
async def add_handoff(request: Request, record: HandoffRecord) -> dict:
    db = request.app.state.db
    saved = await db.add_handoff(record)
    return saved.model_dump(mode="json")


@router.get("/api/v1/run-steps")
async def get_run_steps(
    request: Request,
    task_id: str | None = Query(None),
    run_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    db = request.app.state.db
    records = await db.get_run_steps(task_id=task_id, run_id=run_id, limit=limit)
    return [record.model_dump(mode="json") for record in records]


@router.post("/api/v1/run-steps")
async def add_run_step(request: Request, record: RunStepRecord) -> dict:
    db = request.app.state.db
    saved = await db.add_run_step(record)
    return saved.model_dump(mode="json")


@router.post("/api/v1/runtime/cleanup")
async def cleanup_runtime(
    request: Request,
    max_memories_per_task: int = Query(100, ge=1, le=10_000),
) -> dict:
    db = request.app.state.db
    return await db.cleanup_runtime(max_memories_per_task=max_memories_per_task)


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
            ws_manager.disconnect_agent(agent_id, ws)

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
