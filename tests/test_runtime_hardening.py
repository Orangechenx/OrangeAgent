import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orangeagent.agents.base import BaseAgent
from orangeagent.bus import LocalMessageBus, Message
from orangeagent.runtime.models import MemoryRecord, ToolCallRecord
from orangeagent.server.db import Database
from orangeagent.server.ws_manager import ConnectionManager


@pytest.mark.asyncio
async def test_local_bus_and_server_database_share_runtime_store(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "shared.db")
    await bus.initialize()
    db = Database(tmp_path / "shared.db")
    await db.connect()
    try:
        assert type(bus._store).__name__ == "SQLiteRuntimeStore"
        assert type(db._store).__name__ == "SQLiteRuntimeStore"
    finally:
        await db.close()
        await bus.close()


@pytest.mark.asyncio
async def test_local_bus_drops_oldest_when_subscriber_queue_is_full(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "queue.db", queue_maxsize=1)
    await bus.initialize()
    try:
        queue = bus.subscribe("main_agent")
        await bus.publish(
            Message(from_agent="human", to_agent="main_agent", type="request", content="第一条")
        )
        await bus.publish(
            Message(from_agent="human", to_agent="main_agent", type="request", content="第二条")
        )

        received = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received.content == "第二条"
        assert queue.empty()
    finally:
        await bus.close()


class FailingWebSocket:
    async def accept(self):
        return None

    async def send_json(self, payload):
        raise RuntimeError("连接已断开")


@pytest.mark.asyncio
async def test_websocket_dispatch_removes_dead_agent_and_observer():
    manager = ConnectionManager()
    agent_ws = FailingWebSocket()
    observer_ws = FailingWebSocket()

    await manager.connect_agent(agent_ws, "main_agent")
    await manager.connect_observer(observer_ws)

    await manager.dispatch(
        Message(from_agent="human", to_agent="main_agent", type="request", content="ping"),
        {"main_agent"},
    )

    assert "main_agent" not in manager.active_agent_ids
    assert observer_ws not in manager._observers


@pytest.mark.asyncio
async def test_task_status_transitions_from_running_to_completed(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "task.db")
    await bus.initialize()
    try:
        request = Message(from_agent="human", to_agent="main_agent", type="request", content="分析签名")
        await bus.publish(request)
        tasks = await bus.get_tasks(session_id=request.session_id)
        assert tasks[0].status == "running"

        await bus.publish(
            Message(
                session_id=request.session_id,
                task_id=request.task_id,
                from_agent="trace_agent",
                to_agent="human",
                type="conclusion",
                content="trace line 9 证明使用 HMAC-SHA256",
                evidence=["line 9: sha256 round"],
                confidence="high",
                reply_to=request.id,
            )
        )

        tasks = await bus.get_tasks(session_id=request.session_id)
        assert tasks[0].status == "completed"
        assert tasks[0].phase == "answered"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_verified_memory_supersedes_conflicting_tentative_memory(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "memory.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="分析 X-Sign",
            owner_agent="main_agent",
            goal="确认算法",
        )
        old = await bus.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="tentative",
                source="agent",
                content="X-Sign 使用 AES",
                confidence="low",
            )
        )
        await bus.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="trace",
                content="trace line 9 证明 X-Sign 使用 HMAC-SHA256",
                confidence="high",
                evidence_refs=["ev1"],
            )
        )

        memories = await bus.get_memories(task_id=task.id)
        by_id = {memory.id: memory for memory in memories}
        assert by_id[old.id].status == "superseded"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_tool_call_audit_round_trip(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "tool.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="工具审计",
            owner_agent="trace_agent",
            goal="记录工具调用",
        )
        record = await bus.add_tool_call(
            ToolCallRecord(
                session_id="s1",
                task_id=task.id,
                agent_id="trace_agent",
                tool_name="trace_search",
                arguments={"query": "HMAC", "limit": 5},
                result_preview="line 9: sha256 round",
                status="ok",
                duration_ms=12,
                truncated=False,
            )
        )

        records = await bus.get_tool_calls(task_id=task.id)
        assert records[0].id == record.id
        assert records[0].tool_name == "trace_search"
        assert records[0].arguments["query"] == "HMAC"
    finally:
        await bus.close()


class EchoToolExecutor:
    def execute(self, name, arguments):
        return "line 9: sha256 round"


@pytest.mark.asyncio
async def test_agent_tool_loop_records_tool_call_audit(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "agent_tool.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="工具审计",
            owner_agent="trace_agent",
            goal="记录工具调用",
        )
        agent = BaseAgent(
            agent_id="trace_agent",
            system_prompt="你是 Trace Agent。",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )

        tool_call = MagicMock()
        tool_call.id = "call-1"
        tool_call.function.name = "trace_search"
        tool_call.function.arguments = '{"query": "HMAC", "limit": 5}'

        first = MagicMock()
        first.choices = [MagicMock()]
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool_call]

        second = MagicMock()
        second.choices = [MagicMock()]
        second.choices[0].message.content = "完成"
        second.choices[0].message.tool_calls = None

        with patch(
            "orangeagent.agents.base.litellm.acompletion",
            new=AsyncMock(side_effect=[first, second]),
        ):
            result = await agent.think(
                "搜索 HMAC",
                tools=[{"type": "function", "function": {"name": "trace_search"}}],
                tool_executor=EchoToolExecutor(),
                session_id="s1",
                task_id=task.id,
            )

        records = await bus.get_tool_calls(task_id=task.id)
        assert result == "完成"
        assert records[0].tool_name == "trace_search"
        assert records[0].result_preview == "line 9: sha256 round"
    finally:
        await bus.close()
