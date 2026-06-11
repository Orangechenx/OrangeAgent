import pytest

from orangeagent.bus import LocalMessageBus, Message
from orangeagent.runtime.models import RunStepRecord


@pytest.mark.asyncio
async def test_request_creates_run_record_and_message_step(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "runs.db")
    await bus.initialize()
    try:
        msg = Message(
            session_id="s1",
            run_id="run-1",
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析 X-Sign",
        )
        await bus.publish(msg)

        runs = await bus.get_runs(run_id="run-1")
        steps = await bus.get_run_steps(run_id="run-1")

        assert len(runs) == 1
        assert runs[0].status == "running"
        assert runs[0].phase == "message"
        assert runs[0].task_id == msg.task_id
        assert steps[0].step_type == "message"
        assert steps[0].metadata["message_id"] == msg.id
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_checkpoint_step_updates_run_resume_pointer(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "checkpoint.db")
    await bus.initialize()
    try:
        msg = Message(
            session_id="s1",
            run_id="run-2",
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析签名",
        )
        await bus.publish(msg)
        checkpoint = await bus.add_run_step(
            RunStepRecord(
                session_id="s1",
                task_id=msg.task_id,
                run_id="run-2",
                agent_id="main_agent",
                step_type="checkpoint",
                title="可恢复检查点",
                content="已完成上下文构建",
            )
        )

        runs = await bus.get_runs(run_id="run-2")

        assert runs[0].checkpoint_step_id == checkpoint.id
        assert runs[0].phase == "checkpoint"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_delegated_conclusion_completes_matching_handoff(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "handoff_done.db")
    await bus.initialize()
    try:
        request = Message(
            session_id="s1",
            run_id="run-3",
            from_agent="main_agent",
            mentions=["trace_agent"],
            type="request",
            content="@trace_agent 验证 X-Sign",
        )
        await bus.publish(request)
        await bus.publish(
            Message(
                session_id="s1",
                task_id=request.task_id,
                run_id="run-3",
                from_agent="trace_agent",
                to_agent="main_agent",
                type="conclusion",
                content="trace line 9 证明使用 HMAC",
                evidence=["line 9: HMAC"],
                confidence="high",
                reply_to=request.id,
            )
        )

        handoffs = await bus.get_handoffs(task_id=request.task_id)

        assert handoffs[0].status == "completed"
        assert handoffs[0].result_message_id is not None
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_final_human_conclusion_marks_run_completed(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "run_done.db")
    await bus.initialize()
    try:
        request = Message(
            session_id="s1",
            run_id="run-4",
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析签名",
        )
        await bus.publish(request)
        await bus.publish(
            Message(
                session_id="s1",
                task_id=request.task_id,
                run_id="run-4",
                from_agent="main_agent",
                to_agent="human",
                type="conclusion",
                content="最终结论: trace line 9 证明使用 HMAC",
                evidence=["line 9: HMAC"],
                confidence="high",
                reply_to=request.id,
            )
        )

        runs = await bus.get_runs(run_id="run-4")

        assert runs[0].status == "completed"
        assert runs[0].phase == "answered"
        assert "最终结论" in runs[0].summary
    finally:
        await bus.close()
