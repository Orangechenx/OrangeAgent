from pathlib import Path

from orangeagent.bus.models import Message
from orangeagent.runtime.models import (
    EvidenceRecord,
    HandoffRecord,
    MemoryRecord,
    RunRecord,
    RunStepRecord,
    TaskRecord,
    ToolCallRecord,
)
from orangeagent.runtime.store import SQLiteRuntimeStore


class Database:
    """FastAPI 使用的 SQLite 存储薄包装。"""

    def __init__(self, db_path: Path) -> None:
        self._store = SQLiteRuntimeStore(db_path)

    async def connect(self) -> None:
        await self._store.connect()

    async def close(self) -> None:
        await self._store.close()

    async def prepare_message(self, msg: Message) -> Message:
        return await self._store.prepare_message(msg)

    async def insert_message(self, msg: Message) -> None:
        await self._store.insert_message(msg)

    async def persist_message_with_runtime(self, msg: Message) -> None:
        await self._store.persist_message_with_runtime(msg)

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        return await self._store.get_history(
            limit=limit,
            from_agent=from_agent,
            msg_type=msg_type,
        )

    async def create_task(
        self,
        *,
        session_id: str,
        title: str,
        owner_agent: str = "main_agent",
        goal: str = "",
    ) -> TaskRecord:
        return await self._store.create_task(
            session_id=session_id,
            title=title,
            owner_agent=owner_agent,
            goal=goal,
        )

    async def get_tasks(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        return await self._store.get_tasks(session_id=session_id, limit=limit)

    async def get_runs(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        return await self._store.get_runs(
            session_id=session_id,
            task_id=task_id,
            run_id=run_id,
            limit=limit,
        )

    async def add_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        return await self._store.add_evidence(evidence)

    async def get_evidence(self, *, task_id: str, limit: int = 50) -> list[EvidenceRecord]:
        return await self._store.get_evidence(task_id=task_id, limit=limit)

    async def add_memory(self, memory: MemoryRecord) -> MemoryRecord:
        return await self._store.add_memory(memory)

    async def get_memories(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        return await self._store.get_memories(
            session_id=session_id,
            task_id=task_id,
            limit=limit,
        )

    async def add_tool_call(self, record: ToolCallRecord) -> ToolCallRecord:
        return await self._store.add_tool_call(record)

    async def get_tool_calls(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[ToolCallRecord]:
        return await self._store.get_tool_calls(task_id=task_id, limit=limit)

    async def add_handoff(self, record: HandoffRecord) -> HandoffRecord:
        return await self._store.add_handoff(record)

    async def get_handoffs(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[HandoffRecord]:
        return await self._store.get_handoffs(
            task_id=task_id,
            run_id=run_id,
            limit=limit,
        )

    async def add_run_step(self, record: RunStepRecord) -> RunStepRecord:
        return await self._store.add_run_step(record)

    async def get_run_steps(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[RunStepRecord]:
        return await self._store.get_run_steps(
            task_id=task_id,
            run_id=run_id,
            limit=limit,
        )

    async def build_context(
        self,
        *,
        session_id: str,
        task_id: str | None,
        query: str,
        limit: int = 8,
    ) -> str:
        return await self._store.build_context(
            session_id=session_id,
            task_id=task_id,
            query=query,
            limit=limit,
        )

    async def build_system_context(self, *, limit: int = 15) -> str:
        return await self._store.build_system_context(limit=limit)

    async def get_message(self, msg_id: str) -> Message | None:
        return await self._store.get_message(msg_id)

    async def capture_runtime_records(self, msg: Message) -> None:
        await self._store.capture_runtime_records(msg)

    async def cleanup_runtime(self, *, max_memories_per_task: int = 100) -> dict[str, int]:
        return await self._store.cleanup_runtime(
            max_memories_per_task=max_memories_per_task,
        )
