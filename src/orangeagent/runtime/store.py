import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite
import structlog

from orangeagent.bus.models import Message

from .models import (
    EvidenceRecord,
    HandoffRecord,
    MemoryRecord,
    RunRecord,
    RunStepRecord,
    TaskRecord,
    ToolCallRecord,
    now_utc,
)
from .scoring import score_memory

logger = structlog.get_logger()

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    task_id TEXT,
    run_id TEXT NOT NULL DEFAULT '',
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    mentions TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    reply_to TEXT
)
"""

_CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    owner_agent TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    summary TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    summary TEXT NOT NULL,
    error TEXT,
    checkpoint_step_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT
)
"""

_CREATE_EVIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    ref TEXT NOT NULL,
    content TEXT NOT NULL,
    message_id TEXT,
    tool_call_id TEXT,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_MEMORIES_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_TOOL_CALLS_TABLE = """
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    result_preview TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
"""

_CREATE_HANDOFFS_TABLE = """
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    run_id TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    reason TEXT NOT NULL,
    expected_output TEXT NOT NULL,
    required_evidence TEXT NOT NULL,
    allowed_tools TEXT NOT NULL,
    status TEXT NOT NULL,
    source_message_id TEXT,
    result_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_RUN_STEPS_TABLE = """
CREATE TABLE IF NOT EXISTS run_steps (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    task_id TEXT,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    step_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
"""

_TRACE_LINE_RE = re.compile(r"\bline\s+(\d+)\b", re.IGNORECASE)
_JADX_REF_RE = re.compile(r"\b([\w.$]+)\.([\w$<>]+)\b")


_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_messages_session_task_time "
    "ON messages(session_id, task_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_messages_from_type_time "
    "ON messages(from_agent, type, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_session_updated "
    "ON tasks(session_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_runs_session_updated "
    "ON runs(session_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_runs_task_updated "
    "ON runs(task_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_task_created "
    "ON tool_calls(task_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_handoffs_task_created "
    "ON handoffs(task_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_run_steps_run_created "
    "ON run_steps(run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_run_steps_task_created "
    "ON run_steps(task_id, created_at)",
)

_MEM_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_evidence_task_created "
    "ON evidence(task_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memories_task_status_weight "
    "ON memories(task_id, status, weight)",
)


class SQLiteRuntimeStore:
    """SQLite 存储层，统一负责消息、任务、证据、记忆和工具审计。

    支持可选的分库（memory_db_path），将证据和记忆分离到独立数据库，
    减少写锁竞争（参考 codex-ds 的四库设计）。
    """

    def __init__(
        self,
        db_path: Path,
        memory_db_path: Path | None = None,
        trace_files: dict[str, Path] | None = None,
        jadx_ref_checker: Callable[[str], Awaitable[bool]] | None = None,
        memory_conflict_judge: Callable[[MemoryRecord, MemoryRecord], Awaitable[bool]]
        | None = None,
    ) -> None:
        self._db_path = db_path
        self._memory_db_path = memory_db_path
        self._trace_files = trace_files or {}
        self._jadx_ref_checker = jadx_ref_checker
        self._memory_conflict_judge = memory_conflict_judge
        self._db: aiosqlite.Connection | None = None
        self._mem_db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)

        # 主库：messages, tasks, runs, tool_calls, handoffs, run_steps
        await self._db.execute(_CREATE_MESSAGES_TABLE)
        await self._db.execute(_CREATE_TASKS_TABLE)
        await self._db.execute(_CREATE_RUNS_TABLE)
        await self._db.execute(_CREATE_TOOL_CALLS_TABLE)
        await self._db.execute(_CREATE_HANDOFFS_TABLE)
        await self._db.execute(_CREATE_RUN_STEPS_TABLE)
        for ddl in _CREATE_INDEXES:
            await self._db.execute(ddl)
        await self._migrate_messages()

        # 记忆库（可选分库）：evidence, memories
        if self._memory_db_path:
            self._memory_db_path.parent.mkdir(parents=True, exist_ok=True)
            self._mem_db = await aiosqlite.connect(self._memory_db_path)
            await self._mem_db.execute(_CREATE_EVIDENCE_TABLE)
            await self._mem_db.execute(_CREATE_MEMORIES_TABLE)
            for ddl in _MEM_INDEXES:
                await self._mem_db.execute(ddl)
            await self._mem_db.commit()
        else:
            await self._db.execute(_CREATE_EVIDENCE_TABLE)
            await self._db.execute(_CREATE_MEMORIES_TABLE)
            for ddl in _MEM_INDEXES:
                await self._db.execute(ddl)

        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        if self._mem_db:
            await self._mem_db.close()
            self._mem_db = None

    async def prepare_message(self, msg: Message) -> Message:
        if msg.type in {"request", "question"} and msg.task_id is None:
            task = await self.create_task(
                session_id=msg.session_id,
                title=msg.content[:80] or "未命名任务",
                owner_agent=msg.to_agent or "main_agent",
                goal=msg.content,
            )
            msg.task_id = task.id
            return msg

        if msg.reply_to and msg.task_id is None:
            parent = await self.get_message(msg.reply_to)
            if parent:
                msg.session_id = parent.session_id
                msg.task_id = parent.task_id
        return msg

    async def insert_message(self, msg: Message) -> None:
        db = self._require_db()
        await db.execute(
            "INSERT INTO messages (id, session_id, task_id, run_id, from_agent, "
            "to_agent, mentions, type, content, evidence, confidence, timestamp, reply_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id,
                msg.session_id,
                msg.task_id,
                msg.run_id,
                msg.from_agent,
                msg.to_agent,
                json.dumps(msg.mentions),
                msg.type,
                msg.content,
                json.dumps(msg.evidence),
                msg.confidence,
                msg.timestamp.isoformat(),
                msg.reply_to,
            ),
        )
        await db.commit()

    async def persist_message_with_runtime(self, msg: Message) -> None:
        await self.ensure_run(msg)
        await self.insert_message(msg)
        await self.add_run_step(
            RunStepRecord(
                session_id=msg.session_id,
                task_id=msg.task_id,
                run_id=msg.run_id,
                agent_id=msg.from_agent,
                step_type="message",
                title=f"消息: {msg.type}",
                content=msg.content[:1000],
                metadata={
                    "message_id": msg.id,
                    "to_agent": msg.to_agent,
                    "mentions": msg.mentions,
                },
                status="ok",
            )
        )
        await self.capture_runtime_records(msg)
        await self.capture_handoff_records(msg)

    async def ensure_run(self, msg: Message) -> RunRecord:
        existing = await self.get_run(msg.run_id)
        if existing:
            await self.update_run_status(
                msg.run_id,
                status=existing.status,
                phase="message",
                summary=msg.content[:160],
                task_id=msg.task_id,
            )
            updated = await self.get_run(msg.run_id)
            if updated:
                return updated

        run = RunRecord(
            id=msg.run_id,
            session_id=msg.session_id,
            task_id=msg.task_id,
            status="running",
            phase="message",
            summary=msg.content[:160],
        )
        db = self._require_db()
        await db.execute(
            "INSERT INTO runs (id, session_id, task_id, status, phase, summary, "
            "error, checkpoint_step_id, created_at, updated_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.session_id,
                run.task_id,
                run.status,
                run.phase,
                run.summary,
                run.error,
                run.checkpoint_step_id,
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
                run.ended_at.isoformat() if run.ended_at else None,
            ),
        )
        await db.commit()
        return run

    async def get_run(self, run_id: str) -> RunRecord | None:
        runs = await self.get_runs(run_id=run_id, limit=1)
        return runs[0] if runs else None

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, task_id, run_id, from_agent, to_agent, mentions, "
            "type, content, evidence, confidence, timestamp, reply_to "
            "FROM messages WHERE 1=1"
        )
        params: list[str] = []
        if from_agent:
            query += " AND from_agent = ?"
            params.append(from_agent)
        if msg_type:
            query += " AND type = ?"
            params.append(msg_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return list(reversed([self._row_to_message(row) for row in rows]))

    async def get_message(self, msg_id: str) -> Message | None:
        db = self._require_db()
        async with db.execute(
            "SELECT id, session_id, task_id, run_id, from_agent, to_agent, mentions, "
            "type, content, evidence, confidence, timestamp, reply_to "
            "FROM messages WHERE id = ?",
            (msg_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_message(row) if row else None

    async def create_task(
        self,
        *,
        session_id: str,
        title: str,
        owner_agent: str = "main_agent",
        goal: str = "",
    ) -> TaskRecord:
        task = TaskRecord(
            session_id=session_id,
            title=title,
            owner_agent=owner_agent,
            goal=goal,
        )
        await self._insert_task(task)
        return task

    async def update_task_status(
        self,
        task_id: str,
        *,
        status: str,
        phase: str,
        summary: str = "",
        error: str | None = None,
    ) -> None:
        db = self._require_db()
        await db.execute(
            "UPDATE tasks SET status = ?, phase = ?, summary = COALESCE(NULLIF(?, ''), summary), "
            "error = ?, updated_at = ? WHERE id = ?",
            (status, phase, summary, error, now_utc().isoformat(), task_id),
        )
        await db.commit()

    async def get_tasks(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, title, owner_agent, goal, status, phase, "
            "summary, error, created_at, updated_at FROM tasks WHERE 1=1"
        )
        params: list[str] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def get_runs(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, task_id, status, phase, summary, error, "
            "checkpoint_step_id, created_at, updated_at, ended_at "
            "FROM runs WHERE 1=1"
        )
        params: list[str] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if run_id:
            query += " AND id = ?"
            params.append(run_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_run(row) for row in rows]

    async def update_run_status(
        self,
        run_id: str,
        *,
        status: str,
        phase: str,
        summary: str = "",
        error: str | None = None,
        task_id: str | None = None,
        checkpoint_step_id: str | None = None,
    ) -> None:
        db = self._require_db()
        ended_at = now_utc().isoformat() if status in {"completed", "failed", "cancelled"} else None
        await db.execute(
            "UPDATE runs SET status = ?, phase = ?, "
            "summary = COALESCE(NULLIF(?, ''), summary), "
            "error = COALESCE(?, error), task_id = COALESCE(?, task_id), "
            "checkpoint_step_id = COALESCE(?, checkpoint_step_id), "
            "updated_at = ?, ended_at = COALESCE(?, ended_at) WHERE id = ?",
            (
                status,
                phase,
                summary,
                error,
                task_id,
                checkpoint_step_id,
                now_utc().isoformat(),
                ended_at,
                run_id,
            ),
        )
        await db.commit()

    async def add_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        evidence = await self._validate_evidence(evidence)
        db = self._require_mem_db()
        await db.execute(
            "INSERT INTO evidence (id, session_id, task_id, type, source, ref, "
            "content, message_id, tool_call_id, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.id,
                evidence.session_id,
                evidence.task_id,
                evidence.type,
                evidence.source,
                evidence.ref,
                evidence.content,
                evidence.message_id,
                evidence.tool_call_id,
                evidence.confidence,
                evidence.created_at.isoformat(),
            ),
        )
        await db.commit()
        return evidence

    async def get_evidence(self, *, task_id: str, limit: int = 50) -> list[EvidenceRecord]:
        db = self._require_mem_db()
        async with db.execute(
            "SELECT id, session_id, task_id, type, source, ref, content, "
            "message_id, tool_call_id, confidence, created_at "
            "FROM evidence WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
            (task_id, str(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_evidence(row) for row in rows]

    async def add_memory(self, memory: MemoryRecord) -> MemoryRecord:
        memory.weight = score_memory(memory, task_id=memory.task_id)
        if memory.status == "verified":
            await self._supersede_conflicting_tentative_memories(memory)
        db = self._require_mem_db()
        await db.execute(
            "INSERT INTO memories (id, session_id, task_id, scope, status, source, "
            "content, confidence, evidence_refs, weight, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory.id,
                memory.session_id,
                memory.task_id,
                memory.scope,
                memory.status,
                memory.source,
                memory.content,
                memory.confidence,
                json.dumps(memory.evidence_refs),
                memory.weight,
                memory.created_at.isoformat(),
                memory.updated_at.isoformat(),
            ),
        )
        await db.commit()
        # 自动归档：记忆过多时清理低价值 tentative 记忆
        await self._auto_archive_if_needed()
        return memory

    async def _auto_archive_if_needed(self) -> None:
        """当任务记忆数超过阈值时自动归档低价值 tentatives。

        参考 codex-ds 的定期归档策略：避免长期运行后上下文被旧猜测污染。
        """
        db = self._require_mem_db()
        async with db.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'tentative'"
        ) as cursor:
            (count,) = await cursor.fetchone()
        if count >= 200:
            logger.info("auto_archive_triggered", tentative_count=count)
            await self.cleanup_runtime(max_memories_per_task=100)

    async def get_memories(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        db = self._require_mem_db()
        query = (
            "SELECT id, session_id, task_id, scope, status, source, content, "
            "confidence, evidence_refs, weight, created_at, updated_at "
            "FROM memories WHERE 1=1"
        )
        params: list[str] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        query += " ORDER BY weight DESC, updated_at DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def add_tool_call(self, record: ToolCallRecord) -> ToolCallRecord:
        db = self._require_db()
        await db.execute(
            "INSERT INTO tool_calls (id, session_id, task_id, agent_id, tool_name, "
            "arguments, result_preview, status, error, duration_ms, truncated, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.session_id,
                record.task_id,
                record.agent_id,
                record.tool_name,
                json.dumps(record.arguments),
                record.result_preview,
                record.status,
                record.error,
                record.duration_ms,
                int(record.truncated),
                record.created_at.isoformat(),
            ),
        )
        await db.commit()
        return record

    async def get_tool_calls(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[ToolCallRecord]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, task_id, agent_id, tool_name, arguments, "
            "result_preview, status, error, duration_ms, truncated, created_at "
            "FROM tool_calls WHERE 1=1"
        )
        params: list[str] = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_tool_call(row) for row in rows]

    async def add_handoff(self, record: HandoffRecord) -> HandoffRecord:
        db = self._require_db()
        await db.execute(
            "INSERT INTO handoffs (id, session_id, task_id, run_id, from_agent, "
            "to_agent, reason, expected_output, required_evidence, allowed_tools, "
            "status, source_message_id, result_message_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.session_id,
                record.task_id,
                record.run_id,
                record.from_agent,
                record.to_agent,
                record.reason,
                record.expected_output,
                json.dumps(record.required_evidence, ensure_ascii=False),
                json.dumps(record.allowed_tools, ensure_ascii=False),
                record.status,
                record.source_message_id,
                record.result_message_id,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        await db.commit()
        return record

    async def get_handoffs(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[HandoffRecord]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, task_id, run_id, from_agent, to_agent, reason, "
            "expected_output, required_evidence, allowed_tools, status, "
            "source_message_id, result_message_id, created_at, updated_at "
            "FROM handoffs WHERE 1=1"
        )
        params: list[str] = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_handoff(row) for row in rows]

    async def add_run_step(self, record: RunStepRecord) -> RunStepRecord:
        db = self._require_db()
        await db.execute(
            "INSERT INTO run_steps (id, session_id, task_id, run_id, agent_id, "
            "step_type, title, content, metadata, status, duration_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.session_id,
                record.task_id,
                record.run_id,
                record.agent_id,
                record.step_type,
                record.title,
                record.content,
                json.dumps(record.metadata, ensure_ascii=False),
                record.status,
                record.duration_ms,
                record.created_at.isoformat(),
            ),
        )
        await db.commit()
        if record.step_type == "checkpoint":
            await self.update_run_status(
                record.run_id,
                status="running",
                phase="checkpoint",
                summary=record.title,
                task_id=record.task_id,
                checkpoint_step_id=record.id,
            )
        elif record.status == "error":
            await self.update_run_status(
                record.run_id,
                status="failed",
                phase=record.step_type,
                summary=record.title,
                error=record.content[:500],
                task_id=record.task_id,
            )
        return record

    async def get_run_steps(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[RunStepRecord]:
        db = self._require_db()
        query = (
            "SELECT id, session_id, task_id, run_id, agent_id, step_type, title, "
            "content, metadata, status, duration_ms, created_at "
            "FROM run_steps WHERE 1=1"
        )
        params: list[str] = []
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(str(limit))
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_run_step(row) for row in rows]

    async def cleanup_runtime(self, *, max_memories_per_task: int = 100) -> dict[str, int]:
        """归档每个任务中过量的低价值 tentative 记忆。"""
        db = self._require_mem_db()
        now = now_utc().isoformat()
        archived_memories = 0
        async with db.execute(
            "SELECT DISTINCT task_id FROM memories "
            "WHERE task_id IS NOT NULL AND status = 'tentative'"
        ) as cursor:
            task_rows = await cursor.fetchall()

        for (task_id,) in task_rows:
            async with db.execute(
                "SELECT id, session_id, task_id, scope, status, source, content, "
                "confidence, evidence_refs, weight, created_at, updated_at "
                "FROM memories WHERE task_id = ? AND status = 'tentative' "
                "ORDER BY weight DESC, updated_at DESC",
                (task_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            stale_memories = [self._row_to_memory(row) for row in rows][max_memories_per_task:]
            for memory in stale_memories:
                await db.execute(
                    "UPDATE memories SET status = 'archived', weight = ?, updated_at = ? "
                    "WHERE id = ?",
                    (-0.1, now, memory.id),
                )
                archived_memories += 1

        await db.commit()
        return {"archived_memories": archived_memories}

    async def build_context(
        self,
        *,
        session_id: str,
        task_id: str | None,
        query: str,
        limit: int = 8,
    ) -> str:
        memories = await self.get_memories(session_id=session_id, task_id=task_id)
        ranked = sorted(
            memories,
            key=lambda item: score_memory(item, query=query, task_id=task_id),
            reverse=True,
        )
        positive = [m for m in ranked if m.status not in {"rejected", "superseded"}][:limit]
        rejected = [m for m in ranked if m.status in {"rejected", "superseded"}][:3]
        sections: list[str] = []
        if positive:
            sections.append("## 相关记忆")
            for memory in positive:
                sections.append(
                    f"- [{memory.status}/{memory.source}/{memory.confidence}] {memory.content}"
                )
        if rejected:
            sections.append("## 已否定或替代的记忆（禁止作为依据）")
            for memory in rejected:
                sections.append(f"- [{memory.status}] {memory.content}")
        return "\n".join(sections)

    async def build_system_context(self, *, limit: int = 15) -> str:
        """构建跨 session 的高权重记忆上下文，用于合成进 system prompt。

        参考 Reasonix 的 Block() 设计：记忆作为 system prompt 的稳定上下文，
        而非每次注入 user message。
        """
        memories = await self.get_memories(limit=limit * 2)
        ranked = sorted(
            memories,
            key=lambda m: score_memory(m),
            reverse=True,
        )
        positive = [m for m in ranked if m.status not in {"rejected", "superseded"}][:limit]
        rejected = [m for m in ranked if m.status in {"rejected", "superseded"}][:3]
        sections: list[str] = []
        if positive:
            sections.append("## 持久记忆")
            for memory in positive:
                sections.append(
                    f"- [{memory.status}/{memory.source}/{memory.confidence}] {memory.content}"
                )
        if rejected:
            sections.append("## 已否定或替代的记忆（禁止作为依据）")
            for memory in rejected:
                sections.append(f"- [{memory.status}] {memory.content}")
        return "\n".join(sections)

    # ── 两阶段记忆管道（参考 codex-ds memory pipeline） ────────────

    async def extract_session_memories(self, session_id: str, limit: int = 10) -> list[MemoryRecord]:
        """Stage 1: 从已完成的任务中提取总结性记忆。

        读取 session 最近完成的 task，结合 evidence 和 tool_calls
        生成可复用的高权重记忆。
        """
        db = self._require_db()
        async with db.execute(
            "SELECT id, session_id, title, owner_agent, goal, status, phase, "
            "summary, error, created_at, updated_at FROM tasks "
            "WHERE session_id = ? AND status = 'completed' "
            "ORDER BY updated_at DESC LIMIT ?",
            (session_id, limit),
        ) as cursor:
            task_rows = await cursor.fetchall()
        if not task_rows:
            return []

        mem_db = self._require_mem_db()
        extracted: list[MemoryRecord] = []
        for row in task_rows:
            task = self._row_to_task(row)
            mems = await self.get_memories(session_id=session_id, task_id=task.id, limit=3)
            if mems:
                # 已有记忆，跳过提取
                continue
            # 从 evidence 中提取总结
            evs = await self.get_evidence(task_id=task.id, limit=5)
            if not evs:
                continue
            evidence_lines = [f"- {e.ref}: {e.content[:200]}" for e in evs]
            summary = (task.summary or task.title)[:500]
            memory = MemoryRecord(
                session_id=session_id,
                task_id=task.id,
                scope="task",
                status="tentative",
                source="agent",
                content=f"任务总结: {summary}\n证据:\n" + "\n".join(evidence_lines),
                confidence="high",
                evidence_refs=[e.id for e in evs],
            )
            await self.add_memory(memory)
            extracted.append(memory)
        return extracted

    async def consolidate_global_memories(self, limit: int = 10) -> list[MemoryRecord]:
        """Stage 2: 全局记忆汇聚。

        跨 session 选择最高权重的已确认记忆用于注入 system prompt。
        """
        mem_db = self._require_mem_db()
        async with mem_db.execute(
            "SELECT id, session_id, task_id, scope, status, source, content, "
            "confidence, evidence_refs, weight, created_at, updated_at "
            "FROM memories WHERE status IN ('verified', 'active', 'pinned') "
            "ORDER BY weight DESC, updated_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def capture_runtime_records(self, msg: Message) -> None:
        if msg.type != "conclusion" or not msg.task_id:
            return
        await self._complete_matching_handoff(msg)
        evidence_refs = await self._capture_evidence(msg)
        await self.add_memory(
            MemoryRecord(
                session_id=msg.session_id,
                task_id=msg.task_id,
                scope="task",
                status="verified" if evidence_refs else "tentative",
                source=_source_from_agent(msg.from_agent),
                content=msg.content,
                confidence=msg.confidence,
                evidence_refs=evidence_refs,
            )
        )
        if msg.to_agent == "human":
            await self.update_task_status(
                msg.task_id,
                status="completed",
                phase="answered",
                summary=msg.content[:160],
            )
            await self.update_run_status(
                msg.run_id,
                status="completed",
                phase="answered",
                summary=msg.content[:160],
                task_id=msg.task_id,
            )
        else:
            await self.update_task_status(
                msg.task_id,
                status="running",
                phase="agent_conclusion",
                summary=msg.content[:160],
            )
            await self.update_run_status(
                msg.run_id,
                status="running",
                phase="agent_conclusion",
                summary=msg.content[:160],
                task_id=msg.task_id,
            )

    async def capture_handoff_records(self, msg: Message) -> None:
        if msg.type not in {"request", "question"} or not msg.task_id:
            return
        targets = [agent_id for agent_id in msg.mentions if agent_id != msg.from_agent]
        if msg.to_agent and msg.to_agent != msg.from_agent:
            targets.append(msg.to_agent)
        for target in dict.fromkeys(targets):
            if target == "human":
                continue
            profile = _handoff_profile(target)
            handoff = await self.add_handoff(
                HandoffRecord(
                    session_id=msg.session_id,
                    task_id=msg.task_id,
                    run_id=msg.run_id,
                    from_agent=msg.from_agent,
                    to_agent=target,
                    reason=msg.content,
                    expected_output=profile["expected_output"],
                    required_evidence=profile["required_evidence"],
                    allowed_tools=profile["allowed_tools"],
                    source_message_id=msg.id,
                )
            )
            await self.add_run_step(
                RunStepRecord(
                    session_id=msg.session_id,
                    task_id=msg.task_id,
                    run_id=msg.run_id,
                    agent_id=msg.from_agent,
                    step_type="handoff",
                    title=f"委托 {target}",
                    content=msg.content[:1000],
                    metadata={"handoff_id": handoff.id, "to_agent": target},
                    status="ok",
                )
            )

    async def _capture_evidence(self, msg: Message) -> list[str]:
        refs: list[str] = []
        for raw in msg.evidence:
            evidence = _evidence_from_text(msg, raw)
            if evidence is None:
                continue
            saved = await self.add_evidence(evidence)
            refs.append(saved.id)
        return refs

    async def _complete_matching_handoff(self, msg: Message) -> None:
        db = self._require_db()
        now = now_utc().isoformat()
        await db.execute(
            "UPDATE handoffs SET status = 'completed', result_message_id = ?, updated_at = ? "
            "WHERE id = ("
            "SELECT id FROM handoffs WHERE task_id = ? AND run_id = ? "
            "AND to_agent = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1"
            ")",
            (msg.id, now, msg.task_id, msg.run_id, msg.from_agent),
        )
        await db.commit()

    async def _insert_task(self, task: TaskRecord) -> None:
        db = self._require_db()
        await db.execute(
            "INSERT INTO tasks (id, session_id, title, owner_agent, goal, status, "
            "phase, summary, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.session_id,
                task.title,
                task.owner_agent,
                task.goal,
                task.status,
                task.phase,
                task.summary,
                task.error,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ),
        )
        await db.commit()

    async def _supersede_conflicting_tentative_memories(self, memory: MemoryRecord) -> None:
        if not memory.task_id:
            return
        db = self._require_mem_db()
        verified_tokens = _memory_tokens(memory.content)
        if not verified_tokens and self._memory_conflict_judge is None:
            return
        async with db.execute(
            "SELECT id, session_id, task_id, scope, status, source, content, "
            "confidence, evidence_refs, weight, created_at, updated_at "
            "FROM memories WHERE task_id = ? AND status = 'tentative'",
            (memory.task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        now = now_utc().isoformat()
        for row in rows:
            old_memory = self._row_to_memory(row)
            has_conflict = bool(verified_tokens) and _has_conflict(
                verified_tokens,
                old_memory.content,
            )
            if not has_conflict and self._memory_conflict_judge:
                try:
                    has_conflict = await self._memory_conflict_judge(old_memory, memory)
                except Exception as exc:
                    logger.warning(
                        "记忆冲突判定失败",
                        memory_id=old_memory.id,
                        task_id=memory.task_id,
                        error=str(exc)[:120],
                    )
                    has_conflict = False
            if has_conflict:
                await db.execute(
                    "UPDATE memories SET status = 'superseded', weight = ?, updated_at = ? WHERE id = ?",
                    (-0.2, now, old_memory.id),
                )
        await db.commit()

    async def _validate_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        if evidence.type == "trace_line":
            return self._validate_trace_line_evidence(evidence)
        if evidence.type == "jadx_ref":
            return await self._validate_jadx_ref_evidence(evidence)
        return evidence

    def _validate_trace_line_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        line_match = _TRACE_LINE_RE.search(evidence.ref)
        if not line_match:
            return evidence
        line_number = int(line_match.group(1))
        if self._trace_line_exists(line_number):
            return evidence
        return evidence.model_copy(
            update={
                "confidence": "low",
                "content": f"{evidence.content}\n校验失败: trace 行号 {line_number} 未找到",
            }
        )

    async def _validate_jadx_ref_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        if self._jadx_ref_checker is None:
            return evidence
        try:
            exists = await self._jadx_ref_checker(evidence.ref)
        except Exception as exc:
            return evidence.model_copy(
                update={
                    "confidence": "low",
                    "content": f"{evidence.content}\n校验失败: JADX 引用校验异常: {exc}",
                }
            )
        if exists:
            return evidence
        return evidence.model_copy(
            update={
                "confidence": "low",
                "content": f"{evidence.content}\n校验失败: JADX 引用未验证: {evidence.ref}",
            }
        )

    def _trace_line_exists(self, line_number: int) -> bool:
        if not self._trace_files:
            return True
        for path in self._trace_files.values():
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", errors="replace") as file:
                for index, line in enumerate(file, start=1):
                    if index == line_number:
                        return True
                    if f"line {line_number}" in line.lower():
                        return True
        return False

    async def _migrate_messages(self) -> None:
        db = self._require_db()
        for column, ddl in (
            ("session_id", "ALTER TABLE messages ADD COLUMN session_id TEXT NOT NULL DEFAULT ''"),
            ("task_id", "ALTER TABLE messages ADD COLUMN task_id TEXT"),
            ("run_id", "ALTER TABLE messages ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"),
            ("mentions", "ALTER TABLE messages ADD COLUMN mentions TEXT NOT NULL DEFAULT '[]'"),
        ):
            try:
                await db.execute(f"SELECT {column} FROM messages LIMIT 1")
            except aiosqlite.OperationalError:
                await db.execute(ddl)

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteRuntimeStore 尚未连接")
        return self._db

    def _require_mem_db(self) -> aiosqlite.Connection:
        """返回记忆库连接。如果没分库则返回主库。"""
        if self._mem_db is not None:
            return self._mem_db
        return self._require_db()

    @staticmethod
    def _row_to_message(row: tuple) -> Message:
        return Message(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            run_id=row[3],
            from_agent=row[4],
            to_agent=row[5],
            mentions=json.loads(row[6]),
            type=row[7],
            content=row[8],
            evidence=json.loads(row[9]),
            confidence=row[10],
            timestamp=row[11],
            reply_to=row[12],
        )

    @staticmethod
    def _row_to_task(row: tuple) -> TaskRecord:
        return TaskRecord(
            id=row[0],
            session_id=row[1],
            title=row[2],
            owner_agent=row[3],
            goal=row[4],
            status=row[5],
            phase=row[6],
            summary=row[7],
            error=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

    @staticmethod
    def _row_to_run(row: tuple) -> RunRecord:
        return RunRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            status=row[3],
            phase=row[4],
            summary=row[5],
            error=row[6],
            checkpoint_step_id=row[7],
            created_at=row[8],
            updated_at=row[9],
            ended_at=row[10],
        )

    @staticmethod
    def _row_to_evidence(row: tuple) -> EvidenceRecord:
        return EvidenceRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            type=row[3],
            source=row[4],
            ref=row[5],
            content=row[6],
            message_id=row[7],
            tool_call_id=row[8],
            confidence=row[9],
            created_at=row[10],
        )

    @staticmethod
    def _row_to_memory(row: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            scope=row[3],
            status=row[4],
            source=row[5],
            content=row[6],
            confidence=row[7],
            evidence_refs=json.loads(row[8]),
            weight=row[9],
            created_at=row[10],
            updated_at=row[11],
        )

    @staticmethod
    def _row_to_tool_call(row: tuple) -> ToolCallRecord:
        return ToolCallRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            agent_id=row[3],
            tool_name=row[4],
            arguments=json.loads(row[5]),
            result_preview=row[6],
            status=row[7],
            error=row[8],
            duration_ms=row[9],
            truncated=bool(row[10]),
            created_at=row[11],
        )

    @staticmethod
    def _row_to_handoff(row: tuple) -> HandoffRecord:
        return HandoffRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            run_id=row[3],
            from_agent=row[4],
            to_agent=row[5],
            reason=row[6],
            expected_output=row[7],
            required_evidence=json.loads(row[8]),
            allowed_tools=json.loads(row[9]),
            status=row[10],
            source_message_id=row[11],
            result_message_id=row[12],
            created_at=row[13],
            updated_at=row[14],
        )

    @staticmethod
    def _row_to_run_step(row: tuple) -> RunStepRecord:
        return RunStepRecord(
            id=row[0],
            session_id=row[1],
            task_id=row[2],
            run_id=row[3],
            agent_id=row[4],
            step_type=row[5],
            title=row[6],
            content=row[7],
            metadata=json.loads(row[8]),
            status=row[9],
            duration_ms=row[10],
            created_at=row[11],
        )


def _source_from_agent(agent_id: str) -> str:
    if "trace" in agent_id:
        return "trace"
    if "jadx" in agent_id or "ida" in agent_id:
        return "jadx"
    if agent_id == "human":
        return "user"
    return "agent"


def _handoff_profile(agent_id: str) -> dict[str, list[str] | str]:
    if agent_id == "trace_agent":
        return {
            "expected_output": "返回 trace 证据、关键行号和可验证推理",
            "required_evidence": ["trace 行号"],
            "allowed_tools": ["trace"],
        }
    if agent_id == "ida_jadx_agent":
        return {
            "expected_output": "返回 JADX 类名、方法引用和源码依据",
            "required_evidence": ["JADX 类名或方法引用"],
            "allowed_tools": ["jadx"],
        }
    return {
        "expected_output": "返回可验证结论和下一步建议",
        "required_evidence": ["可定位证据"],
        "allowed_tools": ["analysis"],
    }


def _evidence_from_text(msg: Message, raw: str) -> EvidenceRecord | None:
    if not msg.task_id:
        return None
    evidence_type = "message"
    ref = msg.id
    line_match = _TRACE_LINE_RE.search(raw)
    if line_match:
        evidence_type = "trace_line"
        ref = f"line {line_match.group(1)}"
    elif _JADX_REF_RE.search(raw):
        evidence_type = "jadx_ref"
        ref = raw.split()[0]
    elif raw.strip():
        evidence_type = "tool_result" if raw.lower().startswith("tool") else "message"
        ref = raw[:80]
    return EvidenceRecord(
        session_id=msg.session_id,
        task_id=msg.task_id,
        type=evidence_type,
        source=_source_from_agent(msg.from_agent),
        ref=ref,
        content=raw,
        message_id=msg.id,
        confidence=msg.confidence,
        created_at=now_utc(),
    )


def _memory_tokens(content: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9_+-]{2,}", content)}
    upper = content.upper()
    aliases = {
        "国密": "sm3",
        "摘要": "hash",
        "哈希": "hash",
        "签名": "sign",
    }
    for word, token in aliases.items():
        if word in content:
            tokens.add(token)
    for algorithm in ("SM3", "SM4", "HMAC", "SHA256", "AES", "MD5", "RSA"):
        if algorithm in upper:
            tokens.add(algorithm.lower())
    return tokens


def _has_conflict(verified_tokens: set[str], content: str) -> bool:
    content_tokens = _memory_tokens(content)
    algorithm_tokens = {
        "aes",
        "hmac",
        "sha256",
        "hmac-sha256",
        "md5",
        "rsa",
        "sm3",
        "sm4",
    }
    verified_algorithms = verified_tokens & algorithm_tokens
    content_algorithms = content_tokens & algorithm_tokens
    if not verified_algorithms or not content_algorithms:
        return False
    return verified_algorithms.isdisjoint(content_algorithms)
