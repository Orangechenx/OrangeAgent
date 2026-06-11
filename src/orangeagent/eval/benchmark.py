from pydantic import BaseModel, Field


class EvalResult(BaseModel):
    score: int
    metrics: dict[str, int] = Field(default_factory=dict)
    summary: str
    warnings: list[str] = Field(default_factory=list)


async def evaluate_runtime(bus) -> EvalResult:
    tasks = await bus.get_tasks(limit=500)
    handoffs = await _optional_list(bus, "get_handoffs", limit=500)
    run_steps = await _optional_list(bus, "get_run_steps", limit=1000)
    memories = await bus.get_memories(limit=500)

    evidence_count = 0
    for task in tasks:
        evidence_count += len(await bus.get_evidence(task_id=task.id, limit=500))

    metrics = {
        "tasks": len(tasks),
        "handoffs": len(handoffs),
        "run_steps": len(run_steps),
        "memories": len(memories),
        "evidence": evidence_count,
    }
    score = _score(metrics)
    warnings = _warnings(metrics)
    summary = (
        "runtime 完整度: "
        f"tasks={metrics['tasks']} evidence={metrics['evidence']} "
        f"handoffs={metrics['handoffs']} run_steps={metrics['run_steps']} "
        f"memories={metrics['memories']}"
    )
    return EvalResult(score=score, metrics=metrics, summary=summary, warnings=warnings)


async def _optional_list(bus, method_name: str, **kwargs) -> list:
    method = getattr(bus, method_name, None)
    if method is None:
        return []
    return await method(**kwargs)


def _score(metrics: dict[str, int]) -> int:
    score = 0
    if metrics["tasks"] > 0:
        score += 20
    if metrics["evidence"] > 0:
        score += 25
    if metrics["handoffs"] > 0:
        score += 20
    if metrics["run_steps"] > 0:
        score += 20
    if metrics["memories"] > 0:
        score += 15
    return min(score, 100)


def _warnings(metrics: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    if metrics["tasks"] == 0:
        warnings.append("没有任务记录，无法评估 Agent 运行质量")
    if metrics["evidence"] == 0:
        warnings.append("没有证据记录，结论缺少可验证依据")
    if metrics["handoffs"] == 0:
        warnings.append("没有结构化 handoff，协作链路不可审计")
    if metrics["run_steps"] == 0:
        warnings.append("没有运行步骤，无法复盘 LLM/tool 执行过程")
    return warnings
