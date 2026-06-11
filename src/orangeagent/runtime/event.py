"""事件系统（参考 Reasonix event.Sink 设计）。

Agent 发射类型化事件，前端决定怎么渲染。
解耦 Agent 逻辑和 UI 渲染。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Protocol


class EventKind(str, Enum):
    """事件类型"""
    AGENT_STATUS = "agent_status"       # Agent 状态变化（thinking/tool_calling/idle/error）
    LLM_CALL = "llm_call"               # LLM 调用（含耗时和 token 数）
    TOOL_CALL = "tool_call"             # 工具调用
    MESSAGE = "message"                 # 消息事件
    ERROR = "error"                     # 错误
    CHECKPOINT = "checkpoint"           # 检查点
    CACHE_INFO = "cache_info"           # 缓存命中信息
    MEMORY_EXTRACTED = "memory_extracted"  # 记忆提取


@dataclass
class Event:
    kind: EventKind
    agent_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class Sink(Protocol):
    """消费事件的接口。

    Agent 调用 emit() 发射事件，实现决定怎么处理。
    emit() 不能阻塞——Channel 实现的 Sink 应当有缓冲区。
    """

    def emit(self, event: Event) -> None: ...


class FuncSink:
    """适配普通函数的 Sink。"""

    def __init__(self, func: Callable[[Event], None]) -> None:
        self._func = func

    def emit(self, event: Event) -> None:
        self._func(event)


class DiscardSink:
    """丢弃所有事件（默认行为）。"""

    def emit(self, event: Event) -> None:
        pass


class CallbackSink:
    """带回调注册的事件分发器，多个监听者可以订阅。"""

    def __init__(self) -> None:
        self._callbacks: list[Callable[[Event], None]] = []

    def subscribe(self, cb: Callable[[Event], None]) -> None:
        self._callbacks.append(cb)

    def unsubscribe(self, cb: Callable[[Event], None]) -> None:
        self._callbacks.remove(cb)

    def emit(self, event: Event) -> None:
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass


DISCARD = DiscardSink()
