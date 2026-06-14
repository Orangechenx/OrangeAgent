import asyncio
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from orangeagent.runtime.models import (
    EvidenceRecord,
    HandoffRecord,
    MemoryRecord,
    RunRecord,
    RunStepRecord,
    TaskRecord,
    ToolCallRecord,
)

from .interface import MessageBus
from .models import Message

if TYPE_CHECKING:
    from orangeagent.runtime.store import SQLiteRuntimeStore  # noqa: F401

_DEFAULT_QUEUE_MAXSIZE = 200
_STATUS_CACHE_TTL = 30  # status 内存缓存时长（秒）
_STATUS_CACHE_MAX = 100


class LocalMessageBus(MessageBus):
    def __init__(self, db_path: Path, queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE) -> None:
        from orangeagent.runtime.store import SQLiteRuntimeStore
        self._store = SQLiteRuntimeStore(db_path)
        self._queue_maxsize = queue_maxsize
        self._status_cache: deque[tuple[float, Message]] = deque(maxlen=_STATUS_CACHE_MAX)
        self._subscribers: dict[str, asyncio.Queue[Message]] = {}
        self._observers: list[asyncio.Queue[Message]] = []

    async def initialize(self) -> None:
        await self._store.connect()

    async def close(self) -> None:
        await self._store.close()
        self._subscribers.clear()
        self._observers.clear()

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers[agent_id] = queue
        return queue

    def unsubscribe(self, agent_id: str) -> None:
        self._subscribers.pop(agent_id, None)

    def add_observer(self) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._observers.append(queue)
        return queue

    def remove_observer(self, queue: asyncio.Queue[Message]) -> None:
        try:
            self._observers.remove(queue)
        except ValueError:
            pass

    async def publish(self, msg: Message) -> None:
        msg = await self._store.prepare_message(msg)
        if msg.type != "status":
            await self._store.persist_message_with_runtime(msg)
        else:
            self._cache_status(msg)
        self._dispatch(msg)

    def _cache_status(self, msg: Message) -> None:
        """缓存 status 消息到内存环形缓冲区（带 TTL）。"""
        now = time.monotonic()
        self._status_cache.append((now, msg))
        # 惰性清理过期缓存
        while self._status_cache and now - self._status_cache[0][0] > _STATUS_CACHE_TTL:
            self._status_cache.popleft()

    def get_recent_status(self, max_age: float = _STATUS_CACHE_TTL) -> list[Message]:
        """获取近期 status 消息（供新 observer 初始化用）。"""
        now = time.monotonic()
        return [msg for t, msg in self._status_cache if now - t <= max_age]

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

    async def cleanup_runtime(self, *, max_memories_per_task: int = 100) -> dict[str, int]:
        return await self._store.cleanup_runtime(
            max_memories_per_task=max_memories_per_task,
        )

    def _dispatch(self, msg: Message) -> None:
        recipients: set[str] = set()

        if msg.to_agent:
            recipients.add(msg.to_agent)
        for agent_id in msg.mentions:
            recipients.add(agent_id)
        if not recipients:
            recipients = {agent_id for agent_id in self._subscribers if agent_id != msg.from_agent}
        recipients.discard(msg.from_agent)

        for agent_id in recipients:
            queue = self._subscribers.get(agent_id)
            if queue:
                _put_drop_oldest(queue, msg)
        for observer in self._observers:
            _put_drop_oldest(observer, msg)


def _put_drop_oldest(queue: asyncio.Queue[Message], msg: Message) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(msg)


MessageBus = LocalMessageBus
