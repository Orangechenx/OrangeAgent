"""工具注册表 —— 自注册模式（参考 Hermes ToolRegistry 设计）。

工具通过 @tool 装饰器或 register() 函数注册到全局注册表。
Agent 通过 get_definitions(toolset) 自动发现可用工具。

两种注册方式：
1. @tool 装饰器 — 新工具，handler 自带，可脱离 executor 独立执行
2. register() — 从旧 schema 字典导入，handler 为空（仍走 executor）
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolDef:
    """工具定义"""
    name: str                         # 工具名称
    toolset: str                      # 所属工具集（frida / jadx / trace / …）
    description: str                  # 工具描述
    parameters: dict[str, Any]        # OpenAI function-calling schema 的 parameters
    handler: Callable[..., str] | None = None  # 处理函数（None 表示由 executor 处理）
    check_fn: Callable[[], bool] | None = None  # 可用性检查
    is_async: bool = False


# ── 全局注册表 ────────────────────────────────────────────────

_tools: dict[str, ToolDef] = {}


def register(
    name: str,
    toolset: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[..., str] | None = None,
    *,
    check_fn: Callable[[], bool] | None = None,
) -> None:
    """注册一个工具。

    如果工具已存在且有 handler（来自 @tool 装饰器），
    则 handler=None 的注册（来自 schemas.py 自动导入）不会覆盖。"""
    existing = _tools.get(name)
    if existing is not None and existing.handler is not None and handler is None:
        # @tool 优先：不覆盖已有 handler
        return
    _tools[name] = ToolDef(
        name=name,
        toolset=toolset,
        description=description,
        parameters=parameters,
        handler=handler,
        check_fn=check_fn,
        is_async=handler is not None and inspect.iscoroutinefunction(handler),
    )


def tool(
    name: str,
    toolset: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    *,
    check_fn: Callable[[], bool] | None = None,
) -> Callable:
    """装饰器：将一个普通函数注册为工具。

    用法:
        @tool(name="trace_search", toolset="trace", description="在 trace 中搜索")
        async def trace_search(query: str, file: str, limit: int) -> str:
            ...
    """
    def wrapper(func: Callable) -> Callable:
        params = parameters if parameters is not None else _infer_params(func)
        register(
            name=name,
            toolset=toolset,
            description=description,
            parameters=params,
            handler=func,
            check_fn=check_fn,
        )
        return func
    return wrapper


def get(name: str) -> ToolDef | None:
    """按名称查找工具。"""
    return _tools.get(name)


def get_definitions(toolset: str | None = None) -> list[dict]:
    """返回 OpenAI function-calling 格式的 schema 列表，可选按 toolset 过滤。

    格式与 schemas.py 中的 TRACE_TOOLS / JADX_TOOLS 等完全兼容。
    """
    result: list[dict] = []
    for td in _tools.values():
        if toolset is None or td.toolset == toolset:
            result.append({
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": td.parameters,
                },
            })
    return result


def execute(name: str, arguments: dict[str, Any]) -> str:
    """通过注册表直接执行工具（仅对带 handler 的工具有效）。

    对 handler=None 的工具（仍走 executor 的旧模式），返回错误提示。
    """
    td = _tools.get(name)
    if td is None:
        return json.dumps({"status": "error", "error": f"未知工具: {name}"}, ensure_ascii=False)
    if td.handler is None:
        return json.dumps({
            "status": "error",
            "error": f"工具 '{name}' 无 handler，请通过 executor 执行",
        }, ensure_ascii=False)
    try:
        result = td.handler(**arguments)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


def list_toolsets() -> set[str]:
    """返回所有已注册的工具集名称。"""
    return {td.toolset for td in _tools.values()}


def clear() -> None:
    """清空注册表（仅测试用）。"""
    _tools.clear()


# ── 内部辅助 ──────────────────────────────────────────────────

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _infer_params(func: Callable) -> dict:
    """从简单函数的签名推断 OpenAI function-calling parameters。"""
    sig = inspect.signature(func)
    properties: dict[str, dict] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls", "args", "kwargs"):
            continue
        ptype = _TYPE_MAP.get(param.annotation, "string") if param.annotation != inspect.Parameter.empty else "string"
        properties[pname] = {"type": ptype, "description": pname}
        if param.default == inspect.Parameter.empty:
            required.append(pname)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
