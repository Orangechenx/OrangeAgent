"""假设追踪工具 —— 用于逆向的 Observe → Hypothesize → Test → Verify 循环。

Agent 可以通过这些工具显式记录假设、验证假设、标记 dead end。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from orangeagent.tools.registry import tool


# ── 内存存储（线程安全，生命周期同进程） ──

_hypotheses: dict[str, dict[str, Any]] = {}
_dead_ends: set[str] = set()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@tool(
    name="hypothesis_create",
    toolset="hypothesis",
    description="创建一条假设。在逆向探索中形成猜想时调用，例如猜测加密算法、壳类型、签名算法。",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "假设描述，如'签名算法可能是 HMAC-SHA256'",
            },
            "tags": {
                "type": "string",
                "description": "逗号分隔的标签，如 'aes,vmp,so'",
            },
        },
        "required": ["description"],
    },
)
def hypothesis_create(description: str, tags: str = "") -> str:
    """创建一条假设。"""
    hid = str(len(_hypotheses) + 1)
    _hypotheses[hid] = {
        "id": hid,
        "description": description,
        "status": "active",
        "evidence": [],
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    return json.dumps({
        "status": "ok",
        "hypothesis_id": hid,
        "description": description,
        "message": f"假设已创建: {description}",
    }, ensure_ascii=False)


@tool(
    name="hypothesis_verify",
    toolset="hypothesis",
    description="验证一条假设为真。当找到证据支持假设时调用。",
    parameters={
        "type": "object",
        "properties": {
            "hypothesis_id": {
                "type": "string",
                "description": "假设 ID（从 hypothesis_create 返回）",
            },
            "evidence": {
                "type": "string",
                "description": "验证证据描述，如 'trace 确认使用 AES-128-CBC 指令'",
            },
        },
        "required": ["hypothesis_id", "evidence"],
    },
)
def hypothesis_verify(hypothesis_id: str, evidence: str) -> str:
    """验证一条假设。"""
    h = _hypotheses.get(hypothesis_id)
    if not h:
        return json.dumps({"status": "error", "error": f"假设 {hypothesis_id} 不存在"})
    h["status"] = "verified"
    h["evidence"].append(evidence)
    h["updated_at"] = now_utc()
    return json.dumps({
        "status": "ok",
        "hypothesis_id": hypothesis_id,
        "description": h["description"],
        "message": f"✅ 假设已验证: {h['description']}",
    }, ensure_ascii=False)


@tool(
    name="hypothesis_reject",
    toolset="hypothesis",
    description="拒绝一条假设（标记为 dead end）。当验证失败或发现矛盾证据时调用。",
    parameters={
        "type": "object",
        "properties": {
            "hypothesis_id": {
                "type": "string",
                "description": "假设 ID",
            },
            "reason": {
                "type": "string",
                "description": "拒绝原因，如 'trace 未发现 AES 指令，排除 AES 猜想'",
            },
        },
        "required": ["hypothesis_id", "reason"],
    },
)
def hypothesis_reject(hypothesis_id: str, reason: str) -> str:
    """拒绝一条假设并记录 dead end。"""
    h = _hypotheses.get(hypothesis_id)
    if not h:
        return json.dumps({"status": "error", "error": f"假设 {hypothesis_id} 不存在"})
    h["status"] = "rejected"
    h["evidence"].append(f"[REJECTED] {reason}")
    h["updated_at"] = now_utc()
    # 记录 dead end
    _dead_ends.add(h["description"])
    return json.dumps({
        "status": "ok",
        "hypothesis_id": hypothesis_id,
        "description": h["description"],
        "message": f"❌ 假设已拒绝: {reason}",
    }, ensure_ascii=False)


@tool(
    name="hypothesis_list",
    toolset="hypothesis",
    description="列出当前 session 中所有假设及其状态。用于回顾探索路径、避免重复 dead end。",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "verified", "rejected", "all"],
                "description": "按状态过滤，默认 all",
            },
        },
    },
)
def hypothesis_list(status: str = "all") -> str:
    """列出假设。"""
    items = list(_hypotheses.values())
    if status != "all":
        items = [h for h in items if h["status"] == status]

    if not items:
        return json.dumps({"status": "ok", "hypotheses": [], "count": 0})

    summary = []
    for h in items:
        summary.append({
            "id": h["id"],
            "description": h["description"],
            "status": h["status"],
            "tags": h["tags"],
            "evidence_count": len(h["evidence"]),
        })

    return json.dumps({
        "status": "ok",
        "hypotheses": summary,
        "count": len(summary),
    }, ensure_ascii=False)


@tool(
    name="hypothesis_check_dead_end",
    toolset="hypothesis",
    description="检查某个猜想是否已被标记为 dead end。在开始验证前调用可避免重复踩坑。",
    parameters={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "要检查的猜想描述，如'AES-128-CBC'",
            },
        },
        "required": ["description"],
    },
)
def hypothesis_check_dead_end(description: str) -> str:
    """检查是否为 dead end。"""
    is_dead = description in _dead_ends
    # 模糊匹配
    similar = [d for d in _dead_ends if any(w in d for w in description.split())]
    return json.dumps({
        "status": "ok",
        "is_dead_end": is_dead,
        "description": description,
        "similar_dead_ends": similar[:5],
        "message": "⚠️ 这个路径之前已经走不通了" if is_dead else "✓ 未发现重复",
    }, ensure_ascii=False)
