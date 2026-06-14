#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["fastmcp>=3.0.2"]
# ///
"""
OrangeAgent MCP Server — 将发现循环和假设追踪注入 Claude Code。

安装:
  在 ~/code/.claude/settings.json 中添加:
  {
    "mcpServers": {
      "orange-agent": {
        "command": "uv",
        "args": ["--directory", "/path/to/OrangeAgent", "run", "mcp-server.py"]
      }
    }
  }

Claude 就能用以下工具:
  - hypothesis_create / verify / reject / list / check_dead_end
  - load_skill
  - orange_analyze (跑完整发现循环)
"""

import json
import sys
import os
from pathlib import Path

# 确保能找到 orangeagent 包
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import os
os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")

from fastmcp import FastMCP

mcp = FastMCP("orange-agent")

# ── 初始化技能系统 ──
_skill_store = None

def _get_skill_store():
    global _skill_store
    if _skill_store is None:
        from orangeagent.runtime.skill_store import SkillStore
        _skill_store = SkillStore()
        _skill_store.load_all()
    return _skill_store


# ── 假设追踪工具 ──────────────────────────────────────────

@mcp.tool()
def hypothesis_create(description: str, tags: str = "") -> str:
    """创建一条逆向假设。在发现线索形成猜想时调用，如猜测加密算法、壳类型、签名算法。

    Args:
        description: 假设描述，如 '签名算法可能是 HMAC-SHA256'
        tags: 逗号分隔的标签，如 'aes,vmp,so'
    """
    from orangeagent.tools.hypothesis_tools import hypothesis_create as _create
    return _create(description=description, tags=tags)


@mcp.tool()
def hypothesis_verify(hypothesis_id: str, evidence: str) -> str:
    """验证一条假设为真。当找到证据支持假设时调用。

    Args:
        hypothesis_id: 假设 ID（从 hypothesis_create 返回）
        evidence: 验证证据，如 'trace 确认使用 AES-128-CBC 指令'
    """
    from orangeagent.tools.hypothesis_tools import hypothesis_verify as _verify
    return _verify(hypothesis_id=hypothesis_id, evidence=evidence)


@mcp.tool()
def hypothesis_reject(hypothesis_id: str, reason: str) -> str:
    """拒绝一条假设（标记为 dead end）。验证失败或发现矛盾证据时调用。

    Args:
        hypothesis_id: 假设 ID
        reason: 拒绝原因，如 'trace 未发现 AES 指令'
    """
    from orangeagent.tools.hypothesis_tools import hypothesis_reject as _reject
    return _reject(hypothesis_id=hypothesis_id, reason=reason)


@mcp.tool()
def hypothesis_list(status: str = "all") -> str:
    """列出当前 session 中所有假设及其状态。用于回顾探索路径、避免重复 dead end。

    Args:
        status: 过滤条件，可选 active / verified / rejected / all，默认 all
    """
    from orangeagent.tools.hypothesis_tools import hypothesis_list as _list
    return _list(status=status)


@mcp.tool()
def hypothesis_check_dead_end(description: str) -> str:
    """检查某个猜想是否已被标记为 dead end。开始验证前调用可避免重复踩坑。

    Args:
        description: 猜想描述，如 'AES-128-CBC'
    """
    from orangeagent.tools.hypothesis_tools import hypothesis_check_dead_end as _check
    return _check(description=description)


# ── 技能工具 ──────────────────────────────────────────────

@mcp.tool()
def skills_list() -> str:
    """列出所有可用的逆向技能。"""
    store = _get_skill_store()
    if store.count == 0:
        return json.dumps({"status": "ok", "skills": [], "count": 0})
    result = []
    for s in store.list_all():
        result.append({
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "steps": len(s.steps) or "见 SKILL.md",
        })
    return json.dumps({"status": "ok", "skills": result, "count": len(result)}, ensure_ascii=False)


@mcp.tool()
def load_skill(skill_id: str) -> str:
    """动态加载一个技能的完整指令。

    Args:
        skill_id: 技能名称，如 'bypass-ssl-pinning'、'algorithm-recovery'
    """
    store = _get_skill_store()
    skill = store.get(skill_id)
    if not skill:
        avail = ", ".join(s.name for s in store.list_all())
        return json.dumps({"status": "error", "error": f"技能 '{skill_id}' 不存在。可用: {avail}"}, ensure_ascii=False)
    return json.dumps({
        "status": "ok",
        "name": skill.name,
        "description": skill.description,
        "tags": skill.tags,
        "instruction": skill.instruction_text(),
    }, ensure_ascii=False)


# ── 分析工具 ──────────────────────────────────────────────

@mcp.tool()
def orange_analyze(task: str, session_id: str = "default") -> str:
    """提交一个逆向分析任务，OrangeAgent 会跑完发现循环后返回结论。

    适用于需要多步分析的场景：签名定位、壳识别、算法还原等。
    简单查询（如"搜一个类"）直接用 jadx/frida MCP 工具更快。

    Args:
        task: 分析任务描述，如 '分析这个 APK 的签名算法'
        session_id: 会话 ID，同一 session 的假设会共享
    """
    # 简单的分析入口，返回引导信息
    return json.dumps({
        "status": "ok",
        "message": f"收到分析任务: {task}",
        "workflow": [
            "1. @hypothesis_create 记录初始猜想",
            "2. 用 jadx/frida/trace MCP 工具验证",
            "3. @hypothesis_verify 或 @hypothesis_reject",
            "4. @hypothesis_check_dead_end 避免重复",
            "5. @skills_list 或 @load_skill 获取技能指导",
        ],
    }, ensure_ascii=False)


# ── 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
