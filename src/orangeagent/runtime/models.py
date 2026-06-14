from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


TaskStatus = Literal["running", "waiting", "completed", "failed", "cancelled"]
RunStatus = Literal["running", "waiting", "completed", "failed", "cancelled"]
MemoryScope = Literal["working", "task", "project", "long_term"]
MemoryStatus = Literal[
    "active",
    "pinned",
    "verified",
    "tentative",
    "superseded",
    "rejected",
    "archived",
]
MemorySource = Literal["user", "tool", "trace", "jadx", "agent", "llm"]
EvidenceType = Literal["trace_line", "jadx_ref", "tool_result", "user_note", "message"]
ToolCallStatus = Literal["ok", "error"]
HandoffStatus = Literal["pending", "accepted", "completed", "failed", "cancelled"]
HypothesisStatus = Literal["active", "verified", "rejected"]
RunStepType = Literal[
    "message",
    "handoff",
    "llm",
    "tool",
    "verification",
    "checkpoint",
    "sop",
]
RunStepStatus = Literal["running", "ok", "error", "skipped"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    title: str
    owner_agent: str = "main_agent"
    goal: str = ""
    status: TaskStatus = "running"
    phase: str = "created"
    summary: str = ""
    error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class HypothesisRecord(BaseModel):
    """假设记录 —— 用于追踪逆向过程中的探索假设。

    在逆向的 Observe → Hypothesize → Test → Verify 循环中，
    显式记录"我正在验证什么、结果如何"，避免重复踩坑。
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str | None = None
    agent_id: str = ""
    description: str                                     # "这个签名可能是 HMAC-SHA256"
    status: HypothesisStatus = "active"
    evidence: list[str] = Field(default_factory=list)    # 验证证据列表
    tags: list[str] = Field(default_factory=list)        # 标签（如 ["aes", "vmp"]）
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RunRecord(BaseModel):
    id: str
    session_id: str
    task_id: str | None = None
    status: RunStatus = "running"
    phase: str = "created"
    summary: str = ""
    error: str | None = None
    checkpoint_step_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    ended_at: datetime | None = None


class EvidenceRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str
    type: EvidenceType
    source: MemorySource
    ref: str
    content: str
    message_id: str | None = None
    tool_call_id: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    created_at: datetime = Field(default_factory=now_utc)


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str | None = None
    scope: MemoryScope = "task"
    status: MemoryStatus = "tentative"
    source: MemorySource = "agent"
    content: str
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence_refs: list[str] = Field(default_factory=list)
    weight: float = 0.0
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ToolCallRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str | None = None
    agent_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    result_preview: str = ""
    status: ToolCallStatus = "ok"
    error: str | None = None
    duration_ms: int = 0
    truncated: bool = False
    created_at: datetime = Field(default_factory=now_utc)


class HandoffRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str | None = None
    run_id: str
    from_agent: str
    to_agent: str
    reason: str
    expected_output: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    status: HandoffStatus = "pending"
    source_message_id: str | None = None
    result_message_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RunStepRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    task_id: str | None = None
    run_id: str
    agent_id: str
    step_type: RunStepType
    title: str
    content: str = ""
    metadata: dict = Field(default_factory=dict)
    status: RunStepStatus = "ok"
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=now_utc)
