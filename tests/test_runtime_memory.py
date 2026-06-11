import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orangeagent.agents.base import BaseAgent
from orangeagent.bus import LocalMessageBus, Message
from orangeagent.runtime.models import MemoryRecord
from orangeagent.runtime.scoring import score_memory


@pytest.mark.asyncio
async def test_publish_creates_task_evidence_and_memory(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "runtime.db")
    await bus.initialize()
    try:
        request = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析 X-Sign 的签名算法",
        )
        await bus.publish(request)

        tasks = await bus.get_tasks(session_id=request.session_id)
        assert len(tasks) == 1
        assert request.task_id == tasks[0].id
        assert tasks[0].status == "running"

        conclusion = Message(
            from_agent="trace_agent",
            to_agent="human",
            type="conclusion",
            content="trace line 42 显示调用 HMAC-SHA256 轮函数",
            evidence=["line 42: sha256 round constant"],
            confidence="high",
            reply_to=request.id,
        )
        await bus.publish(conclusion)

        evidence = await bus.get_evidence(task_id=request.task_id)
        assert len(evidence) == 1
        assert evidence[0].type == "trace_line"
        assert evidence[0].ref == "line 42"

        memories = await bus.get_memories(task_id=request.task_id)
        assert any(memory.status == "verified" for memory in memories)

        context = await bus.build_context(
            session_id=request.session_id,
            task_id=request.task_id,
            query="X-Sign HMAC",
        )
        assert "trace line 42" in context
        assert "HMAC-SHA256" in context
    finally:
        await bus.close()


def test_score_memory_prefers_verified_tool_evidence_over_tentative_guess():
    verified = MemoryRecord(
        session_id="s1",
        task_id="t1",
        scope="task",
        status="verified",
        source="trace",
        content="trace line 42 证明使用 HMAC-SHA256",
        confidence="high",
        evidence_refs=["ev1"],
    )
    tentative = MemoryRecord(
        session_id="s1",
        task_id="t1",
        scope="task",
        status="tentative",
        source="agent",
        content="可能是 AES",
        confidence="low",
    )

    assert score_memory(verified, query="X-Sign HMAC", task_id="t1") > score_memory(
        tentative,
        query="X-Sign HMAC",
        task_id="t1",
    )


@pytest.mark.asyncio
async def test_context_marks_rejected_memory_as_forbidden(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "runtime.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="分析签名",
            owner_agent="main_agent",
            goal="确认 X-Sign 算法",
        )
        await bus.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="rejected",
                source="agent",
                content="X-Sign 使用 AES",
                confidence="medium",
            )
        )
        await bus.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="jadx",
                content="SignUtil.sign 使用 Mac.getInstance('HmacSHA256')",
                confidence="high",
                evidence_refs=["ev1"],
            )
        )

        context = await bus.build_context(
            session_id="s1",
            task_id=task.id,
            query="X-Sign 算法",
        )

        assert "SignUtil.sign" in context
        assert "禁止作为依据" in context
        assert "X-Sign 使用 AES" in context
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_agent_think_injects_runtime_context(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "runtime.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="分析签名",
            owner_agent="main_agent",
            goal="确认 X-Sign 算法",
        )
        await bus.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="trace",
                content="trace line 42 证明 X-Sign 使用 HMAC-SHA256",
                confidence="high",
            )
        )
        agent = BaseAgent(
            agent_id="main_agent",
            system_prompt="你是主 Agent。",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_response.choices[0].message.tool_calls = None

        with patch("orangeagent.agents.base.litellm.acompletion", new=AsyncMock(return_value=mock_response)) as mock_llm:
            result = await agent.think(
                "继续分析",
                session_id="s1",
                task_id=task.id,
            )

        assert result == "ok"
        messages = mock_llm.call_args.kwargs["messages"]
        # 记忆合成进 system prompt（而非 user message）
        assert "trace line 42" in messages[0]["content"]
        assert "继续分析" in messages[1]["content"]
    finally:
        await bus.close()
