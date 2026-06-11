import asyncio
from pathlib import Path

import pytest

from orangeagent.bus.http_client import HttpMessageBus
from orangeagent.bus.models import Message
from orangeagent.runtime.models import EvidenceRecord, MemoryRecord
from orangeagent.runtime.store import SQLiteRuntimeStore


@pytest.mark.asyncio
async def test_http_bus_reconnects_after_reader_exits(monkeypatch):
    bus = HttpMessageBus(server_url="http://test:8720", reconnect_delay=0.01)
    calls = 0

    class ClosingWebSocket:
        async def __aiter__(self):
            if False:
                yield ""

    async def fake_connect():
        nonlocal calls
        calls += 1
        bus._ws = ClosingWebSocket()
        bus._connected = True

    monkeypatch.setattr(bus, "_connect_ws", fake_connect)
    bus._ws = ClosingWebSocket()

    await bus._ws_reader()
    await asyncio.sleep(0.02)

    assert calls == 1


@pytest.mark.asyncio
async def test_runtime_store_creates_query_indexes(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "indexed.db")
    await store.connect()
    try:
        db = store._require_db()
        async with db.execute("PRAGMA index_list(messages)") as cursor:
            message_indexes = {row[1] for row in await cursor.fetchall()}
        async with db.execute("PRAGMA index_list(memories)") as cursor:
            memory_indexes = {row[1] for row in await cursor.fetchall()}

        assert "idx_messages_session_task_time" in message_indexes
        assert "idx_memories_task_status_weight" in memory_indexes
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_evidence_validation_marks_missing_trace_line_low_confidence(tmp_path):
    trace_file = tmp_path / "trace.txt"
    trace_file.write_text("line 1: start\nline 2: end\n")
    store = SQLiteRuntimeStore(tmp_path / "evidence.db", trace_files={"code": trace_file})
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="证据校验", goal="校验 trace")
        saved = await store.add_evidence(
            EvidenceRecord(
                session_id="s1",
                task_id=task.id,
                type="trace_line",
                source="trace",
                ref="line 99",
                content="line 99: missing",
                confidence="high",
            )
        )

        assert saved.confidence == "low"
        assert "未找到" in saved.content
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_conflict_detects_chinese_algorithm_names(tmp_path):
    store = SQLiteRuntimeStore(tmp_path / "memory.db")
    await store.connect()
    try:
        task = await store.create_task(session_id="s1", title="冲突检测", goal="确认算法")
        old = await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="tentative",
                source="agent",
                content="X-Sign 使用国密 SM3",
                confidence="low",
            )
        )
        await store.add_memory(
            MemoryRecord(
                session_id="s1",
                task_id=task.id,
                scope="task",
                status="verified",
                source="jadx",
                content="源码确认 X-Sign 使用 HMAC-SHA256",
                confidence="high",
            )
        )

        memories = await store.get_memories(task_id=task.id)
        by_id = {memory.id: memory for memory in memories}
        assert by_id[old.id].status == "superseded"
    finally:
        await store.close()
