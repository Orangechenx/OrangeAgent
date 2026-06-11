from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orangeagent.agents.base import BaseAgent
from orangeagent.bus import LocalMessageBus, Message
from orangeagent.runtime.models import HandoffRecord, RunStepRecord


@pytest.mark.asyncio
async def test_request_mentions_create_structured_handoff(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "handoff.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="分析 X-Sign",
            owner_agent="main_agent",
            goal="确认签名算法",
        )
        await bus.publish(
            Message(
                session_id="s1",
                task_id=task.id,
                run_id="run-1",
                from_agent="main_agent",
                to_agent=None,
                mentions=["trace_agent"],
                type="request",
                content="@trace_agent 请从 trace 验证 X-Sign 是否使用 HMAC",
                evidence=["用户要求分析签名算法"],
                confidence="high",
            )
        )

        handoffs = await bus.get_handoffs(task_id=task.id)

        assert len(handoffs) == 1
        assert handoffs[0].from_agent == "main_agent"
        assert handoffs[0].to_agent == "trace_agent"
        assert handoffs[0].status == "pending"
        assert "trace" in handoffs[0].allowed_tools
        assert "trace 行号" in handoffs[0].required_evidence
        assert "X-Sign" in handoffs[0].reason
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_agent_think_records_llm_tool_and_checkpoint_steps(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "steps.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="步骤审计",
            owner_agent="trace_agent",
            goal="记录运行步骤",
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
        tool_call.function.arguments = '{"query": "HMAC", "from_line": 1, "limit": 5}'

        first = MagicMock()
        first.choices = [MagicMock()]
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool_call]

        second = MagicMock()
        second.choices = [MagicMock()]
        second.choices[0].message.content = "trace line 9 证明使用 HMAC"
        second.choices[0].message.tool_calls = None

        executor = MagicMock()
        executor.execute.return_value = "line 9: HMAC"

        with patch(
            "orangeagent.agents.base.litellm.acompletion",
            new=AsyncMock(side_effect=[first, second]),
        ):
            await agent.think(
                "搜索 HMAC",
                tools=[{"type": "function", "function": {"name": "trace_search"}}],
                tool_executor=executor,
                session_id="s1",
                task_id=task.id,
                run_id="run-2",
            )

        steps = await bus.get_run_steps(run_id="run-2")
        step_types = [step.step_type for step in steps]

        assert "checkpoint" in step_types
        assert step_types.count("llm") == 2
        assert "tool" in step_types
        assert any("tools=True" in step.content for step in steps if step.step_type == "checkpoint")
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_tool_guardrail_blocks_unapproved_tool_and_audits_failure(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "guardrail.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="工具策略",
            owner_agent="trace_agent",
            goal="拒绝危险工具",
        )
        agent = BaseAgent(
            agent_id="trace_agent",
            system_prompt="你是 Trace Agent。",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )

        tool_call = MagicMock()
        tool_call.id = "call-evil"
        tool_call.function.name = "shell_exec"
        tool_call.function.arguments = '{"cmd": "rm -rf /"}'

        first = MagicMock()
        first.choices = [MagicMock()]
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool_call]

        second = MagicMock()
        second.choices = [MagicMock()]
        second.choices[0].message.content = "已拒绝危险工具"
        second.choices[0].message.tool_calls = None

        executor = MagicMock()

        with patch(
            "orangeagent.agents.base.litellm.acompletion",
            new=AsyncMock(side_effect=[first, second]),
        ):
            result = await agent.think(
                "尝试危险工具",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
                tool_executor=executor,
                session_id="s1",
                task_id=task.id,
                run_id="run-3",
            )

        records = await bus.get_tool_calls(task_id=task.id)
        steps = await bus.get_run_steps(run_id="run-3")

        assert result == "已拒绝危险工具"
        executor.execute.assert_not_called()
        assert records[0].status == "error"
        assert "工具策略拒绝" in (records[0].error or "")
        assert any(step.status == "error" and step.step_type == "tool" for step in steps)
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_handoff_and_run_step_round_trip_in_store(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "round_trip.db")
    await bus.initialize()
    try:
        handoff = await bus.add_handoff(
            HandoffRecord(
                session_id="s1",
                task_id="t1",
                run_id="r1",
                from_agent="main_agent",
                to_agent="ida_jadx_agent",
                reason="搜索 SignUtil",
                expected_output="返回类名和方法引用",
                required_evidence=["JADX 类名或方法引用"],
                allowed_tools=["jadx"],
            )
        )
        step = await bus.add_run_step(
            RunStepRecord(
                session_id="s1",
                task_id="t1",
                run_id="r1",
                agent_id="ida_jadx_agent",
                step_type="handoff",
                title="委托静态分析",
                content="搜索 SignUtil",
                metadata={"handoff_id": handoff.id},
                status="ok",
            )
        )

        handoffs = await bus.get_handoffs(task_id="t1")
        steps = await bus.get_run_steps(run_id="r1")

        assert handoffs[0].id == handoff.id
        assert handoffs[0].allowed_tools == ["jadx"]
        assert steps[0].id == step.id
        assert steps[0].metadata["handoff_id"] == handoff.id
    finally:
        await bus.close()
