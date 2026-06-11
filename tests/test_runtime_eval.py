import pytest

from orangeagent.bus import LocalMessageBus, Message
from orangeagent.eval.benchmark import evaluate_runtime
from orangeagent.runtime.models import EvidenceRecord, RunStepRecord


@pytest.mark.asyncio
async def test_runtime_eval_scores_evidence_handoffs_and_steps(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "eval.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="评估",
            owner_agent="main_agent",
            goal="评估 runtime 完整度",
        )
        await bus.publish(
            Message(
                session_id="s1",
                task_id=task.id,
                run_id="r1",
                from_agent="main_agent",
                mentions=["trace_agent"],
                type="request",
                content="@trace_agent 验证签名算法",
            )
        )
        await bus.add_evidence(
            EvidenceRecord(
                session_id="s1",
                task_id=task.id,
                type="trace_line",
                source="trace",
                ref="line 9",
                content="line 9: HMAC",
                confidence="high",
            )
        )
        await bus.add_run_step(
            RunStepRecord(
                session_id="s1",
                task_id=task.id,
                run_id="r1",
                agent_id="trace_agent",
                step_type="llm",
                title="LLM 推理",
                content="完成",
            )
        )

        result = await evaluate_runtime(bus)

        assert result.score >= 60
        assert result.metrics["tasks"] == 1
        assert result.metrics["handoffs"] == 1
        assert result.metrics["evidence"] == 1
        assert result.metrics["run_steps"] >= 1
        assert "runtime 完整度" in result.summary
    finally:
        await bus.close()
