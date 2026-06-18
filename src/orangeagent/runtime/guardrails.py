from dataclasses import dataclass
from typing import Any

from orangeagent.tools.registry import get as _get_tool


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str = ""


# 各 agent 允许的工具域（第二道防线，与 BaseAgent._allowed_toolsets 呼应）。
# main_agent 不在表中 = 无域限制（协调者，全部放行）。
_AGENT_TOOL_DOMAINS = {
    "trace_agent": {"trace"},
    "ida_jadx_agent": {"jadx"},
    "frida_agent": {"frida"},
    "network_agent": {"network"},
    "apktool_agent": {"apktool"},
    "js_reverse_agent": {"js_reverse"},
    "ida_agent": {"ida"},
    "unidbg_agent": {"unidbg"},
}

# 任何 agent 都可调用的公共域（假设追踪、技能加载等跨领域基础设施）。
_COMMON_DOMAINS = {"hypothesis", "skill"}


def _domain_of(tool_name: str) -> str | None:
    """从 registry 动态解析工具所属域；未注册返回 None。"""
    td = _get_tool(tool_name)
    return td.toolset if td is not None else None


def check_tool_policy(
    *,
    agent_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    allowed_domains: set[str] | None = None,
) -> ToolDecision:
    """工具调用策略检查（第二道防线）。

    设计原则：默认放行、只拦明确越界。早期版本硬编码工具域表且未登记即拒绝，
    导致 frida/network/apktool/ida/unidbg/js_reverse 六类 agent 调自身工具时
    被全部拦死。现改为从 registry 动态解析域，未登记工具放行（交由 executor 兜底）。
    """
    domain = _domain_of(tool_name)

    # 公共域工具任何 agent 都可用，跳过域隔离检查
    if domain not in _COMMON_DOMAINS:
        agent_domains = _AGENT_TOOL_DOMAINS.get(agent_id)
        # agent_domains 为 None = 无限制（如 main_agent）；
        # domain 为 None = 未登记工具，放行交给 executor 处理
        if agent_domains is not None and domain is not None and domain not in agent_domains:
            return ToolDecision(False, f"工具策略拒绝: {agent_id} 无权使用 {domain} 工具")

    if allowed_domains is not None and domain is not None and domain not in allowed_domains:
        return ToolDecision(False, f"工具策略拒绝: 当前 handoff 未授权 {domain} 工具")

    if _looks_destructive(arguments):
        return ToolDecision(False, "工具策略拒绝: 参数包含高风险操作")

    return ToolDecision(True)


def _looks_destructive(arguments: dict[str, Any]) -> bool:
    text = " ".join(str(value).lower() for value in arguments.values())
    risky_tokens = ("rm -rf", "format ", "delete ", "drop table", "shutdown")
    return any(token in text for token in risky_tokens)
