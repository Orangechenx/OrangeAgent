"""工具模块出口。

向后兼容：旧模式（import schema 列表 + executor 类）仍然可用。
新模式：通过 registry 自注册，Agent 自动发现。
"""

from .hypothesis_tools import (  # noqa: F401 — @tool 装饰器自注册
    hypothesis_create, hypothesis_verify, hypothesis_reject,
    hypothesis_list, hypothesis_check_dead_end,
)
from .skill_loader import set_skill_store  # noqa: F401
from .trace_executor import LocalTraceToolExecutor
from .jadx_executor import JadxToolExecutor
from .frida_executor import FridaToolExecutor
from .network_executor import NetworkToolExecutor
from .apktool_executor import ApkToolExecutor
from .js_reverse_executor import JsReverseExecutor
from .ida_executor import IdaToolExecutor
from .unidbg_executor import UnidbgToolExecutor
from .schemas import (
    TRACE_TOOLS, JADX_TOOLS, FRIDA_TOOLS, NETWORK_TOOLS,
    APKTOOL_TOOLS, JS_REVERSE_TOOLS, IDA_TOOLS, UNIDBG_TOOLS,
)
from .registry import (
    ToolDef,
    register,
    tool,
    get,
    get_definitions,
    execute,
    list_toolsets,
    clear as _clear_registry,
)

__all__ = [
    "ToolExecutor",
    "LocalTraceToolExecutor",
    "JadxToolExecutor",
    "FridaToolExecutor",
    "NetworkToolExecutor",
    "ApkToolExecutor",
    "JsReverseExecutor",
    "IdaToolExecutor",
    "UnidbgToolExecutor",
    "TRACE_TOOLS",
    "JADX_TOOLS",
    "FRIDA_TOOLS",
    "NETWORK_TOOLS",
    "APKTOOL_TOOLS",
    "JS_REVERSE_TOOLS",
    "IDA_TOOLS",
    "UNIDBG_TOOLS",
    # 注册表
    "ToolDef",
    "register",
    "tool",
    "get",
    "get_definitions",
    "execute",
    "list_toolsets",
    "register_tools_from_schemas",
    "_register_from_schema",
]


# ── 向后兼容：将 schemas.py 中的现有工具自动注册到 registry ──

_TOOLSET_MAP: dict[str, list[dict]] = {
    "trace": TRACE_TOOLS,
    "jadx": JADX_TOOLS,
    "frida": FRIDA_TOOLS,
    "network": NETWORK_TOOLS,
    "apktool": APKTOOL_TOOLS,
    "js_reverse": JS_REVERSE_TOOLS,
    "ida": IDA_TOOLS,
    "unidbg": UNIDBG_TOOLS,
}


def _register_from_schema(tool_dict: dict, toolset: str) -> None:
    """从旧格式的 schema 字典注册一个工具到 registry。"""
    func = tool_dict.get("function", {})
    register(
        name=func.get("name", "unknown"),
        toolset=toolset,
        description=func.get("description", ""),
        parameters=func.get("parameters", {"type": "object", "properties": {}}),
        handler=None,  # 旧工具走 executor，不设 handler
    )


def register_tools_from_schemas() -> None:
    """将 schemas.py 中所有工具批量注册到 registry。"""
    for toolset, tool_list in _TOOLSET_MAP.items():
        for t in tool_list:
            _register_from_schema(t, toolset)


# ── 模块加载时自动注册 ──
register_tools_from_schemas()
