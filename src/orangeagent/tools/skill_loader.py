"""技能加载工具 —— Agent 可在对话中动态加载技能。

注册为 toolset="skill" 的工具，Agent 通过 load_skill 动态拉取技能指令。
与启动时注入的技能目录配合使用：目录告诉 Agent 有哪些技能可用，
load_skill 拉取完整内容。
"""

from __future__ import annotations

import json

from orangeagent.tools.registry import register


# load_skill 需要 SkillStore 实例，通过全局变量注入
_skill_store = None  # type: ignore


def set_skill_store(store) -> None:
    """注入 SkillStore 实例（在 Agent 初始化时调用）。"""
    global _skill_store
    _skill_store = store


def _load_skill(skill_id: str) -> str:
    """加载指定技能的完整指令。"""
    global _skill_store
    if _skill_store is None:
        return json.dumps({"status": "error", "error": "技能系统未初始化"}, ensure_ascii=False)
    skill = _skill_store.get(skill_id)
    if not skill:
        return json.dumps({"status": "error", "error": f"技能 '{skill_id}' 不存在。可用技能：{', '.join(s.name for s in _skill_store.list_all())}"}, ensure_ascii=False)
    return json.dumps({
        "status": "ok",
        "name": skill.name,
        "description": skill.description,
        "tags": skill.tags,
        "instruction": skill.instruction_text(),
        "steps": skill.steps[:8],
    }, ensure_ascii=False)


# 注册 load_skill 工具
register(
    name="load_skill",
    toolset="skill",
    description="动态加载一个技能的完整指令。先通过技能目录了解有哪些技能可用，然后用此工具加载。",
    parameters={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "技能 ID/名称，如 'bypass-ssl-pinning'",
            },
        },
        "required": ["skill_id"],
    },
    handler=_load_skill,
)
