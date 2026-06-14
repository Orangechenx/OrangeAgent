"""事件系统（参考 Reasonix event.Sink + Hermes StreamEvent 设计）。

设计原则：
  一个 Event 类，通过 kind 区分类型。
  工厂函数提供结构化构造，避免 dataclass 继承的字段顺序问题。
  Sink 接口解耦 Agent 逻辑和 UI 渲染。
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
    MIDDLEWARE = "middleware"           # 中间件拦截
    SKILL_MATCHED = "skill_matched"     # 技能匹配
    HYPOTHESIS = "hypothesis"           # 假设追踪


@dataclass
class Event:
    """事件——宇宙唯一的事件类型。

    所有事件都用这一个类，通过 kind 区分。
    data 里放结构化信息，需要时可以解包。
    没有继承，没有字段顺序问题，简单可靠。
    """
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


# ── 工厂函数（结构化构造，替代子类继承） ─────────────────


def agent_status_event(
    agent_id: str,
    state: str,
    task_summary: str = "",
) -> Event:
    """构建 Agent 状态变化事件。"""
    return Event(
        kind=EventKind.AGENT_STATUS,
        agent_id=agent_id,
        data={"state": state, "task_summary": task_summary},
    )


def llm_call_event(
    agent_id: str,
    model: str = "",
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    total_tokens: int = 0,
    duration_ms: int = 0,
    cache_hit_ratio: float = 0.0,
) -> Event:
    """构建 LLM 调用事件。"""
    return Event(
        kind=EventKind.LLM_CALL,
        agent_id=agent_id,
        data={
            "model": model,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens,
            "duration_ms": duration_ms,
            "cache_hit_ratio": cache_hit_ratio,
        },
    )


def tool_call_event(
    agent_id: str,
    tool_name: str = "",
    arguments: dict[str, Any] | None = None,
    result_preview: str = "",
    status: str = "ok",
    error: str | None = None,
    duration_ms: int = 0,
    truncated: bool = False,
) -> Event:
    """构建工具调用事件。"""
    return Event(
        kind=EventKind.TOOL_CALL,
        agent_id=agent_id,
        data={
            "tool_name": tool_name,
            "arguments": arguments or {},
            "result_preview": result_preview[:200],
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
            "truncated": truncated,
        },
    )


def cache_info_event(
    agent_id: str,
    total_tokens: int = 0,
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    cache_hit_ratio: float = 0.0,
) -> Event:
    """构建缓存诊断事件。"""
    return Event(
        kind=EventKind.CACHE_INFO,
        agent_id=agent_id,
        data={
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "cache_hit_ratio": cache_hit_ratio,
        },
    )


def message_event(
    agent_id: str,
    content: str = "",
    msg_type: str = "",
) -> Event:
    """构建消息事件。"""
    return Event(
        kind=EventKind.MESSAGE,
        agent_id=agent_id,
        data={"content": content[:200], "msg_type": msg_type},
    )


def memory_event(
    agent_id: str,
    memory_id: str = "",
    content: str = "",
) -> Event:
    """构建记忆事件。"""
    return Event(
        kind=EventKind.MEMORY_EXTRACTED,
        agent_id=agent_id,
        data={"memory_id": memory_id, "content": content[:200]},
    )


def middleware_event(
    agent_id: str,
    middleware_name: str = "",
    action: str = "",
    detail: str = "",
) -> Event:
    """构建中间件事件。"""
    return Event(
        kind=EventKind.MIDDLEWARE,
        agent_id=agent_id,
        data={
            "middleware_name": middleware_name,
            "action": action,
            "detail": detail[:200],
        },
    )


# ── Sink 接口与实现 ──────────────────────────────────────────


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
