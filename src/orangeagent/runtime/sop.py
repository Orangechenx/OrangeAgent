_ANDROID_REVERSE_SOP = (
    "## 逆向 SOP\n"
    "1. 静态入口搜索: 先定位类名、方法名、字符串和调用点。\n"
    "2. trace 关联: 用 trace 行号验证运行时路径和关键参数。\n"
    "3. 算法假设: 只提出能被源码或 trace 验证的候选算法。\n"
    "4. 证据验证: 中高置信结论必须带 trace 行号或 JADX 方法引用。\n"
    "5. 反证检查: 主动标记被推翻的旧猜测，禁止继续作为依据。\n"
    "6. 最终结论: 输出入口、算法、证据、剩余不确定点。"
)

_AGENT_HINTS = {
    "trace_agent": "当前角色重点: trace 行号、寄存器/内存流、调用序列。",
    "ida_jadx_agent": "当前角色重点: JADX 类名、方法源码、调用引用。",
    "main_agent": "当前角色重点: 分解任务、结构化 handoff、汇总结论。",
}


def build_reverse_sop_context(agent_id: str) -> str:
    hint = _AGENT_HINTS.get(agent_id, "当前角色重点: 输出可验证证据。")
    return f"{_ANDROID_REVERSE_SOP}\n\n{hint}"
