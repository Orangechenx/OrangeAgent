import pytest

from orangeagent.bus.http_client import HttpMessageBus
from orangeagent.runtime.models import EvidenceRecord, MemoryRecord
from orangeagent.runtime.store import SQLiteRuntimeStore


@pytest.mark.asyncio
async def test_jadx_evidence_validator_marks_missing_reference_low_confidence(tmp_path):
    async def fake_jadx_check(ref: str) -> bool:
        return False

    store = SQLiteRuntimeStore(tmp_path / "jadx.db", jadx_ref_checker=fake_jadx_check)
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="JADX 校验", goal="校验引用")
        saved = await store.add_evidence(
            EvidenceRecord(
                session_id="s1",
                task_id=task.id,
                type="jadx_ref",
                source="jadx",
                ref="com.example.SignUtil.sign",
                content="com.example.SignUtil.sign",
                confidence="high",
            )
        )

        assert saved.confidence == "low"
        assert "JADX 引用未验证" in saved.content
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_http_bus_reconnect_uses_exponential_backoff_and_stops_at_limit():
    bus = HttpMessageBus(
        server_url="http://test:8720",
        reconnect_delay=0.01,
        reconnect_max_delay=0.04,
        reconnect_max_attempts=3,
    )
    attempts = 0
    sleeps: list[float] = []

    async def failing_connect():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("server down")

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    bus._connect_ws = failing_connect
    bus._sleep = fake_sleep

    await bus._reconnect_loop()

    assert attempts == 3
    assert sleeps == [0.01, 0.02, 0.04]
    assert bus._reconnect_attempts == 3


@pytest.mark.asyncio
async def test_memory_conflict_uses_optional_llm_judge(tmp_path):
    async def judge(old: MemoryRecord, new: MemoryRecord) -> bool:
        assert "RC4" in old.content
        assert "HMAC-SHA256" in new.content
        return True

    store = SQLiteRuntimeStore(tmp_path / "conflict.db", memory_conflict_judge=judge)
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="冲突", goal="确认算法")
        old = await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="tentative",
                source="agent",
                content="签名算法可能是 RC4 自定义摘要",
                confidence="low",
            )
        )
        await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="trace",
                content="trace line 10 证明签名算法是 HMAC-SHA256",
                confidence="high",
            )
        )

        memories = await store.get_memories(task_id=task.id)
        by_id = {memory.id: memory for memory in memories}
        assert by_id[old.id].status == "superseded"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_conflict_judge_failure_does_not_block_verified_memory(tmp_path):
    async def broken_judge(old: MemoryRecord, new: MemoryRecord) -> bool:
        raise RuntimeError("judge timeout")

    store = SQLiteRuntimeStore(tmp_path / "judge_failure.db", memory_conflict_judge=broken_judge)
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="冲突", goal="确认算法")
        old = await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="tentative",
                source="agent",
                content="签名算法可能是 RC4 自定义摘要",
                confidence="low",
            )
        )

        saved = await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="trace",
                content="trace line 10 证明签名算法是 HMAC-SHA256",
                confidence="high",
            )
        )

        memories = await store.get_memories(task_id=task.id)
        by_id = {memory.id: memory for memory in memories}
        assert saved.status == "verified"
        assert by_id[old.id].status == "tentative"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_runtime_cleanup_archives_old_low_value_records(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "cleanup.db")
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="清理", goal="清理旧记录")
        for index in range(5):
            await store.add_memory(
                MemoryRecord(
                    session_id="s1",
                    task_id=task.id,
                    scope="task",
                    status="tentative",
                    source="agent",
                    content=f"旧猜测 {index}",
                    confidence="low",
                )
            )

        result = await store.cleanup_runtime(max_memories_per_task=2)
        memories = await store.get_memories(task_id=task.id, limit=10)
        archived = [memory for memory in memories if memory.status == "archived"]

        assert result["archived_memories"] == 3
        assert len(archived) == 3
    finally:
        await store.close()
