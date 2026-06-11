from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str = ""


_TOOL_DOMAINS = {
    "trace_search": "trace",
    "trace_context": "trace",
    "trace_cross_ref": "trace",
    "jadx_search_classes_by_keyword": "jadx",
    "jadx_get_class_source": "jadx",
    "jadx_get_method_by_name": "jadx",
    "jadx_get_xrefs_to_class": "jadx",
    "jadx_get_xrefs_to_method": "jadx",
    "jadx_get_methods_of_class": "jadx",
    "jadx_get_fields_of_class": "jadx",
    "jadx_get_android_manifest": "jadx",
    "jadx_get_smali_of_class": "jadx",
    "jadx_get_strings": "jadx",
    "jadx_get_main_activity_class": "jadx",
}

_AGENT_TOOL_DOMAINS = {
    "trace_agent": {"trace"},
    "ida_jadx_agent": {"jadx"},
}


def check_tool_policy(
    *,
    agent_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    allowed_domains: set[str] | None = None,
) -> ToolDecision:
    domain = _TOOL_DOMAINS.get(tool_name)
    if domain is None:
        return ToolDecision(False, f"工具策略拒绝: 未登记工具 {tool_name}")

    agent_domains = _AGENT_TOOL_DOMAINS.get(agent_id)
    if agent_domains is not None and domain not in agent_domains:
        return ToolDecision(False, f"工具策略拒绝: {agent_id} 无权使用 {domain} 工具")

    if allowed_domains is not None and domain not in allowed_domains:
        return ToolDecision(False, f"工具策略拒绝: 当前 handoff 未授权 {domain} 工具")

    if _looks_destructive(arguments):
        return ToolDecision(False, "工具策略拒绝: 参数包含高风险操作")

    return ToolDecision(True)


def _looks_destructive(arguments: dict[str, Any]) -> bool:
    text = " ".join(str(value).lower() for value in arguments.values())
    risky_tokens = ("rm -rf", "format ", "delete ", "drop table", "shutdown")
    return any(token in text for token in risky_tokens)
