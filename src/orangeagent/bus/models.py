from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str | None = None
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    from_agent: str
    to_agent: str | None = None
    mentions: list[str] = Field(default_factory=list)
    type: Literal["conclusion", "request", "question", "decision", "status"]
    content: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "high"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: str | None = None
