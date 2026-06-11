import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orangeagent.agents.base import BaseAgent
from orangeagent.bus import LocalMessageBus, Message
from orangeagent.bus.http_client import HttpMessageBus


@pytest.mark.asyncio
async def test_http_bus_reader_drops_oldest_when_queue_is_full():
    bus = HttpMessageBus(server_url="http://test:8720", queue_maxsize=1)
    queue = bus.subscribe("main_agent")

    first = Message(from_agent="human", to_agent="main_agent", type="request", content="第一条")
    second = Message(from_agent="human", to_agent="main_agent", type="request", content="第二条")

    class FakeWebSocket:
        async def __aiter__(self):
            for msg in (first, second):
                yield '{"type": "message", "data": ' + msg.model_dump_json() + "}"

    bus._ws = FakeWebSocket()
    await bus._ws_reader()

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.content == "第二条"
    assert queue.empty()


@pytest.mark.asyncio
async def test_malformed_tool_arguments_are_audited_instead_of_crashing(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "bad_tool.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="坏工具参数",
            owner_agent="trace_agent",
            goal="审计坏参数",
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
        tool_call.function.arguments = "{bad json"

        first = MagicMock()
        first.choices = [MagicMock()]
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool_call]

        second = MagicMock()
        second.choices = [MagicMock()]
        second.choices[0].message.content = "已处理"
        second.choices[0].message.tool_calls = None

        with patch(
            "orangeagent.agents.base.litellm.acompletion",
            new=AsyncMock(side_effect=[first, second]),
        ):
            result = await agent.think(
                "搜索",
                tools=[{"type": "function", "function": {"name": "trace_search"}}],
                tool_executor=object(),
                session_id="s1",
                task_id=task.id,
            )

        records = await bus.get_tool_calls(task_id=task.id)
        assert result == "已处理"
        assert records[0].status == "error"
        assert "JSON" in (records[0].error or "")
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_internal_agent_conclusion_does_not_complete_task(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "task_status.db")
    await bus.initialize()
    try:
        request = Message(from_agent="human", to_agent="main_agent", type="request", content="分析")
        await bus.publish(request)
        await bus.publish(
            Message(
                session_id=request.session_id,
                task_id=request.task_id,
                from_agent="trace_agent",
                to_agent="main_agent",
                type="conclusion",
                content="trace line 1 初步显示 HMAC",
                evidence=["line 1: hmac"],
                confidence="medium",
                reply_to=request.id,
            )
        )

        tasks = await bus.get_tasks(session_id=request.session_id)
        assert tasks[0].status == "running"
        assert tasks[0].phase == "agent_conclusion"
    finally:
        await bus.close()
