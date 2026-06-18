"""JS Reverse tool executor — JavaScript 反混淆/格式化/分析。

迁移状态：
  部分工具已通过 @tool 装饰器注册到 registry（优先走 registry.execute）。
  execute() 先查 registry，有 handler 则委托执行，无则走本地方法。
"""

from __future__ import annotations

import json
import re
import subprocess
import shutil
from typing import Any

from orangeagent.tools.registry import tool, get


# ── 通过 @tool 注册的工具（优先于 executor 本地方法） ──────────

@tool(name="js_extract_strings", toolset="js_reverse",
      description="从 JS 代码中提取所有字符串字面量。",
      parameters={
          "type": "object",
          "properties": {
              "code": {"type": "string", "description": "JS 代码"},
          },
          "required": ["code"],
      })
def js_extract_strings(code: str) -> str:
    """从 JS 代码中提取所有字符串字面量。"""
    if not code:
        return json.dumps({"status": "error", "error": "需要 code 参数"})
    strings = list(dict.fromkeys(re.findall(r'"([^"]{4,})"|\'([^\']{4,})\'', code)))
    flat = [s[0] or s[1] for s in strings]
    return json.dumps({"status": "ok", "strings": flat[:100], "count": len(flat)})


@tool(name="js_deobfuscate", toolset="js_reverse",
      description="反混淆 JS 代码：解码 \\\\x 转义、恢复可读性。",
      parameters={
          "type": "object",
          "properties": {
              "code": {"type": "string", "description": "混淆的 JS 代码"},
          },
          "required": ["code"],
      })
def js_deobfuscate(code: str) -> str:
    """反混淆 JS 代码（纯函数，无外部依赖）。"""
    if not code:
        return json.dumps({"status": "error", "error": "需要 code 参数"})
    result = code
    result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
    result = re.sub(r'\[(\d+)\]', lambda m: f'[{m.group(1)}]', result)
    return json.dumps({"status": "ok", "deobfuscated": result[:10000]})


# ── Executor 类（保持向后兼容） ──────────────────────────────


class JsReverseExecutor:
    """JavaScript deobfuscation and analysis via js-beautify / node.

    execute() 优先委托 registry，如果工具未在 registry 注册
    （如 js_format 依赖 self._node），则走本地 if/elif 路径。
    """

    def __init__(self) -> None:
        self._node = shutil.which("node")
        self._beautify = None

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        # 优先通过 registry 执行（@tool 注册的工具自带 handler）
        td = get(name)
        if td and td.handler:
            try:
                return td.handler(**arguments)
            except Exception as exc:
                return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

        # 回退到本地 if/elif（仅对仍有状态依赖的工具）
        try:
            if name == "js_format":
                return self._format(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _format(self, args: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code:
            return json.dumps({"status": "error", "error": "需要 code 参数"})
        if not self._node:
            return json.dumps({"status": "ok", "formatted": code, "note": "node 未安装，返回原文"})
        # 通过 stdin 把源码喂给 node，不再写临时文件：
        # 旧实现把 tempfile 路径字面拼进 JS 字符串，Windows 反斜杠/路径含单引号
        # 会破坏 JS 语法导致静默回退原文；且 delete=False 无清理会泄漏临时文件
        node_script = (
            "const b=require('js-beautify');"
            "let s='';process.stdin.on('data',d=>s+=d);"
            "process.stdin.on('end',()=>process.stdout.write(b(s)))"
        )
        try:
            result = subprocess.run(
                [self._node, "-e", node_script],
                input=code, capture_output=True, text=True, timeout=10,
            )
            formatted = result.stdout or code
        except Exception:
            formatted = code
        return json.dumps({"status": "ok", "formatted": formatted[:10000]})

    def close(self) -> None:
        pass
