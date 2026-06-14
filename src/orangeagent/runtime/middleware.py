"""中间件管道（参考 Hermes middleware 设计）。

在 BaseAgent.think() 的工具调用前后插入拦截点：
  tool_request  — 工具调用前，可改写参数或阻止执行
  tool_response — 工具返回后，可记录/改写结果

用法:
    from orangeagent.runtime import MiddlewarePipeline

    pipeline = MiddlewarePipeline()

    @pipeline.on_tool_request
    def inject_context(name, args):
        # 自动注入当前逆向上下文
        args.setdefault("device_id", "usb")
        return args

    @pipeline.on_tool_response
    def audit_log(name, args, result, duration_ms):
        logger.info("tool_call", name=name, duration_ms=duration_ms)
"""

from __future__ import annotations

import functools
import json
from typing import Any, Callable

from orangeagent.runtime.event import (
    Event, EventKind, Sink, DISCARD,
    middleware_event,
)

# ── 类型别名 ──────────────────────────────────────────────────

# tool_request handler: (name, args) -> args | None  (None = block)
ToolRequestHandler = Callable[[str, dict[str, Any]], dict[str, Any] | None]
# tool_response handler: (name, args, result, duration_ms) -> result | None
ToolResponseHandler = Callable[[str, dict[str, Any], str, int], str | None]


class MiddlewareResult:
    """中间件处理结果。"""

    def __init__(
        self,
        allowed: bool = True,
        modified_args: dict[str, Any] | None = None,
        modified_result: str | None = None,
        reason: str = "",
    ) -> None:
        self.allowed = allowed
        self.modified_args = modified_args
        self.modified_result = modified_result
        self.reason = reason


class MiddlewareHandler:
    """单个中间件处理器（带元数据）。"""

    def __init__(
        self,
        name: str,
        request_handler: ToolRequestHandler | None = None,
        response_handler: ToolResponseHandler | None = None,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.request_handler = request_handler
        self.response_handler = response_handler
        self.enabled = enabled


class MiddlewarePipeline:
    """中间件管道，维护有序的中间件链。

    支持两类拦截点：
    1. tool_request  — 在工具执行前，可修改参数或阻止调用
    2. tool_response — 在工具返回后，可记录或修改结果
    """

    def __init__(self, sink: Sink | None = None) -> None:
        self._handlers: list[MiddlewareHandler] = []
        self._sink = sink or DISCARD

    # ── 注册 API ──────────────────────────────────────────

    def use(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        """注册一个中间件。"""
        self._handlers.append(handler)
        return handler

    def on_tool_request(
        self, fn: ToolRequestHandler | None = None, *, name: str = ""
    ) -> ToolRequestHandler | Callable[[ToolRequestHandler], ToolRequestHandler]:
        """装饰器：注册一个 tool_request 中间件。

        用法:
            @pipeline.on_tool_request
            def my_mw(name, args):
                ...
        """
        def decorator(func: ToolRequestHandler) -> ToolRequestHandler:
            mw_name = name or func.__name__
            self._handlers.append(MiddlewareHandler(
                name=mw_name, request_handler=func,
            ))
            return func
        if fn is None:
            return decorator
        return decorator(fn)

    def on_tool_response(
        self, fn: ToolResponseHandler | None = None, *, name: str = ""
    ) -> ToolResponseHandler | Callable[[ToolResponseHandler], ToolResponseHandler]:
        """装饰器：注册一个 tool_response 中间件。"""
        def decorator(func: ToolResponseHandler) -> ToolResponseHandler:
            mw_name = name or func.__name__
            self._handlers.append(MiddlewareHandler(
                name=mw_name, response_handler=func,
            ))
            return func
        if fn is None:
            return decorator
        return decorator(fn)

    def remove(self, name: str) -> None:
        """按名称移除中间件。"""
        self._handlers[:] = [h for h in self._handlers if h.name != name]

    def clear(self) -> None:
        """清空所有中间件。"""
        self._handlers.clear()

    # ── 执行点 ──────────────────────────────────────────

    def on_tool_call_request(
        self, name: str, arguments: dict[str, Any]
    ) -> MiddlewareResult:
        """在工具执行前调用。返回 allowed + 可能修改后的参数。"""
        modified_args = dict(arguments)
        for handler in self._handlers:
            if not handler.enabled or handler.request_handler is None:
                continue
            try:
                result = handler.request_handler(name, modified_args)
                if result is None:
                    self._sink.emit(middleware_event(
                        agent_id="system",
                        middleware_name=handler.name,
                        action="block",
                        detail=f"中间件 {handler.name} 阻止了工具 {name}",
                    ))
                    return MiddlewareResult(
                        allowed=False,
                        reason=f"中间件 '{handler.name}' 阻止了此次调用",
                    )
                modified_args = result
            except Exception as exc:
                self._sink.emit(middleware_event(
                    agent_id="system",
                    middleware_name=handler.name,
                    action="error",
                    detail=f"中间件 {handler.name} 异常: {exc}",
                ))
        return MiddlewareResult(allowed=True, modified_args=modified_args)

    def on_tool_call_response(
        self, name: str, arguments: dict[str, Any],
        result: str, duration_ms: int,
    ) -> str:
        """在工具返回后调用。可修改结果。"""
        modified_result = result
        for handler in self._handlers:
            if not handler.enabled or handler.response_handler is None:
                continue
            try:
                resp = handler.response_handler(name, arguments, modified_result, duration_ms)
                if resp is not None:
                    modified_result = resp
            except Exception as exc:
                self._sink.emit(middleware_event(
                    agent_id="system",
                    middleware_name=handler.name,
                    action="error",
                    detail=f"中间件 {handler.name} 响应处理异常: {exc}",
                ))
        return modified_result

    @property
    def handlers(self) -> list[MiddlewareHandler]:
        return list(self._handlers)


# ── 内置中间件工厂 ──────────────────────────────────────────


def audit_middleware(sink: Sink | None = None) -> MiddlewareHandler:
    """审计日志中间件：记录所有工具调用的入参出参。"""
    _sink = sink or DISCARD

    def on_response(name: str, args: dict, result: str, duration_ms: int) -> None:
        _sink.emit(Event(
            kind=EventKind.TOOL_CALL,
            agent_id="system",
            data={
                "tool": name,
                "args": args,
                "result_preview": result[:200],
                "duration_ms": duration_ms,
            },
        ))

    return MiddlewareHandler(
        name="audit",
        response_handler=on_response,
    )


def inject_context_middleware(
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> MiddlewareHandler:
    """上下文注入中间件：自动给工具调用加上指定参数。"""
    extra = dict(context or {})
    extra.update(kwargs)

    def on_request(name: str, args: dict[str, Any]) -> dict[str, Any]:
        merged = dict(args)
        for k, v in extra.items():
            merged.setdefault(k, v)
        return merged

    return MiddlewareHandler(
        name="inject_context",
        request_handler=on_request,
    )


# ── ToolStormBreaker（参考 Kun ToolStormBreaker） ─────────


class ToolStormBreaker:
    """工具风暴抑制器：检测并抑制重复工具调用。

    在逆向场景中，Agent 经常对 trace/JADX 反复搜索相似内容，
    浪费大量 token。StormBreaker 维护一个滑动窗口，
    相同工具+相同参数出现超过阈值时自动抑制。

    参考 Kun tool-storm-breaker.ts 设计。
    """

    def __init__(
        self,
        window_size: int = 8,
        threshold: int = 3,
        exempt_tools: set[str] | None = None,
    ) -> None:
        self._window: list[tuple[str, frozenset[tuple[str, Any]]]] = []
        self._window_size = window_size
        self._threshold = threshold
        self._exempt = exempt_tools or {"hypothesis_create", "hypothesis_verify",
                                        "hypothesis_reject", "hypothesis_list"}

    def check(self, name: str, arguments: dict[str, Any]) -> bool:
        """检查是否应该抑制此调用。返回 True = 抑制。"""
        if name in self._exempt:
            return False

        sig = (name, _freeze_args(arguments))
        self._window.append(sig)
        if len(self._window) > self._window_size:
            self._window.pop(0)

        count = sum(1 for s in self._window if s == sig)
        return count >= self._threshold

    def reset(self) -> None:
        """重置窗口（新 turn 时调用）。"""
        self._window.clear()


def _freeze_args(args: dict[str, Any]) -> frozenset[tuple[str, Any]]:
    """冻结参数字典用于比较。"""
    items: list[tuple[str, Any]] = []
    for k, v in sorted(args.items()):
        if isinstance(v, str) and len(v) > 200:
            v = v[:200]  # 只比较前 200 字符
        items.append((k, v))
    return frozenset(items)


def storm_breaker_middleware(
    breaker: ToolStormBreaker | None = None,
) -> MiddlewareHandler:
    """创建工具风暴抑制中间件。"""
    _breaker = breaker or ToolStormBreaker()

    def on_request(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if _breaker.check(name, args):
            return None  # 阻止调用
        return args

    return MiddlewareHandler(
        name="storm_breaker",
        request_handler=on_request,
    )
