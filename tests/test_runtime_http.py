import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orangeagent.bus.http_client import HttpMessageBus
from orangeagent.runtime.models import HandoffRecord, MemoryRecord, RunStepRecord, ToolCallRecord
from orangeagent.server.db import Database
from orangeagent.server.routes import router
from orangeagent.server.ws_manager import ConnectionManager


@pytest.fixture
def client(tmp_path):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(db_path=tmp_path / "runtime_http.db")
        await db.connect()
        app.state.db = db
        app.state.ws_manager = ConnectionManager()
        yield
        await db.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_server_runtime_endpoints_create_and_expose_memory(client):
    request = {
        "from_agent": "human",
        "to_agent": "main_agent",
        "type": "request",
        "content": "分析 X-Sign",
        "evidence": [],
        "confidence": "high",
    }
    publish_resp = client.post("/api/v1/publish", json=request)
    assert publish_resp.status_code == 200

    history = client.get("/api/v1/history").json()
    task_id = history[0]["task_id"]
    session_id = history[0]["session_id"]

    conclusion = {
        "session_id": session_id,
        "task_id": task_id,
        "from_agent": "trace_agent",
        "to_agent": "human",
        "type": "conclusion",
        "content": "trace line 88 证明 X-Sign 使用 HMAC-SHA256",
        "evidence": ["line 88: sha256 round"],
        "confidence": "high",
    }
    assert client.post("/api/v1/publish", json=conclusion).status_code == 200

    tasks = client.get(f"/api/v1/tasks?session_id={session_id}").json()
    assert tasks[0]["id"] == task_id

    evidence = client.get(f"/api/v1/evidence?task_id={task_id}").json()
    assert evidence[0]["ref"] == "line 88"

    memories = client.get(f"/api/v1/memories?task_id={task_id}").json()
    assert memories[0]["status"] == "verified"

    context = client.get(
        "/api/v1/context",
        params={"session_id": session_id, "task_id": task_id, "query": "X-Sign HMAC"},
    ).json()
    assert "line 88" in context["context"]


def test_server_publish_captures_handoff_and_run_step(client):
    request = {
        "session_id": "s1",
        "run_id": "run-http-1",
        "from_agent": "main_agent",
        "mentions": ["trace_agent"],
        "type": "request",
        "content": "@trace_agent 验证 X-Sign",
        "evidence": [],
        "confidence": "high",
    }
    publish_resp = client.post("/api/v1/publish", json=request)
    assert publish_resp.status_code == 200

    history = client.get("/api/v1/history").json()
    task_id = history[0]["task_id"]
    handoffs = client.get(f"/api/v1/handoffs?task_id={task_id}").json()
    steps = client.get("/api/v1/run-steps?run_id=run-http-1").json()

    assert handoffs[0]["to_agent"] == "trace_agent"
    assert any(step["step_type"] == "handoff" for step in steps)
    assert any(step["step_type"] == "message" for step in steps)


def test_server_tool_call_endpoints_round_trip(client):
    payload = ToolCallRecord(
        session_id="s1",
        task_id="t1",
        agent_id="trace_agent",
        tool_name="trace_search",
        arguments={"query": "HMAC"},
        result_preview="line 9",
        status="ok",
        duration_ms=3,
        truncated=False,
    ).model_dump(mode="json")

    post_resp = client.post("/api/v1/tool-calls", json=payload)
    assert post_resp.status_code == 200

    records = client.get("/api/v1/tool-calls?task_id=t1").json()
    assert records[0]["tool_name"] == "trace_search"
    assert records[0]["arguments"]["query"] == "HMAC"


def test_server_handoff_and_run_step_endpoints_round_trip(client):
    handoff_payload = HandoffRecord(
        session_id="s1",
        task_id="t1",
        run_id="r1",
        from_agent="main_agent",
        to_agent="trace_agent",
        reason="验证签名算法",
        expected_output="返回 trace 行号",
        required_evidence=["trace 行号"],
        allowed_tools=["trace"],
    ).model_dump(mode="json")
    step_payload = RunStepRecord(
        session_id="s1",
        task_id="t1",
        run_id="r1",
        agent_id="trace_agent",
        step_type="checkpoint",
        title="构建上下文",
        content="逆向 SOP",
        metadata={"phase": "start"},
    ).model_dump(mode="json")

    assert client.post("/api/v1/handoffs", json=handoff_payload).status_code == 200
    assert client.post("/api/v1/run-steps", json=step_payload).status_code == 200

    handoffs = client.get("/api/v1/handoffs?task_id=t1").json()
    steps = client.get("/api/v1/run-steps?run_id=r1").json()

    assert handoffs[0]["to_agent"] == "trace_agent"
    assert handoffs[0]["allowed_tools"] == ["trace"]
    assert steps[0]["step_type"] == "checkpoint"
    assert steps[0]["metadata"]["phase"] == "start"


def test_server_runtime_cleanup_endpoint_archives_excess_memories(client):
    request = {
        "from_agent": "human",
        "to_agent": "main_agent",
        "type": "request",
        "content": "清理 runtime",
        "evidence": [],
        "confidence": "high",
    }
    assert client.post("/api/v1/publish", json=request).status_code == 200
    history = client.get("/api/v1/history").json()
    task_id = history[0]["task_id"]
    session_id = history[0]["session_id"]

    for index in range(5):
        payload = MemoryRecord(
            session_id=session_id,
            task_id=task_id,
            scope="task",
            status="tentative",
            source="agent",
            content=f"旧猜测 {index}",
            confidence="low",
        ).model_dump(mode="json")
        assert client.post("/api/v1/memories", json=payload).status_code == 200

    resp = client.post(
        "/api/v1/runtime/cleanup",
        params={"max_memories_per_task": 2},
    )

    assert resp.status_code == 200
    assert resp.json()["archived_memories"] == 3


@pytest.mark.asyncio
async def test_http_message_bus_runtime_methods(monkeypatch):
    bus = HttpMessageBus(server_url="http://test:8720")

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    async def fake_get(self, url, params=None):
        calls.append((url, params))
        if url.endswith("/api/v1/context"):
            return Response({"context": "记忆上下文"})
        if url.endswith("/api/v1/tasks"):
            return Response([])
        if url.endswith("/api/v1/evidence"):
            return Response([])
        if url.endswith("/api/v1/memories"):
            return Response([])
        if url.endswith("/api/v1/handoffs"):
            return Response([])
        if url.endswith("/api/v1/run-steps"):
            return Response([])
        return Response([])

    async def fake_post(self, url, json=None, params=None):
        calls.append((url, params))
        if url.endswith("/api/v1/runtime/cleanup"):
            return Response({"archived_memories": 2})
        return Response({})

    bus._http = type("HTTP", (), {"get": fake_get, "post": fake_post})()

    assert await bus.build_context(session_id="s1", task_id="t1", query="q") == "记忆上下文"
    assert await bus.get_tasks(session_id="s1") == []
    assert await bus.get_evidence(task_id="t1") == []
    assert await bus.get_memories(task_id="t1") == []
    assert await bus.get_handoffs(task_id="t1") == []
    assert await bus.get_run_steps(run_id="r1") == []
    assert await bus.cleanup_runtime(max_memories_per_task=2) == {"archived_memories": 2}
    assert calls[0][0] == "http://test:8720/api/v1/context"
