"""JS Reverse tool executor — JavaScript 反混淆/格式化/分析。"""

from __future__ import annotations

import json
import re
import subprocess
import shutil
import tempfile
from typing import Any


class JsReverseExecutor:
    """JavaScript deobfuscation and analysis via js-beautify / node."""

    def __init__(self) -> None:
        self._node = shutil.which("node")
        self._beautify = None

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "js_format":
                return self._format(arguments)
            if name == "js_extract_strings":
                return self._extract_strings(arguments)
            if name == "js_deobfuscate":
                return self._deobfuscate(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _format(self, args: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code:
            return json.dumps({"status": "error", "error": "需要 code 参数"})
        if not self._node:
            return json.dumps({"status": "ok", "formatted": code, "note": "node 未安装，返回原文"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            f.flush()
            try:
                result = subprocess.run(
                    [self._node, "-e", f"const b=require('js-beautify');console.log(b(require('fs').readFileSync('{f.name}','utf8')))"],
                    capture_output=True, text=True, timeout=10,
                )
                formatted = result.stdout or code
            except Exception:
                formatted = code
            return json.dumps({"status": "ok", "formatted": formatted[:10000]})

    def _extract_strings(self, args: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code:
            return json.dumps({"status": "error", "error": "需要 code 参数"})
        strings = list(dict.fromkeys(re.findall(r'"([^"]{4,})"|\'([^\']{4,})\'', code)))
        flat = [s[0] or s[1] for s in strings]
        return json.dumps({"status": "ok", "strings": flat[:100], "count": len(flat)})

    def _deobfuscate(self, args: dict[str, Any]) -> str:
        code = args.get("code", "")
        if not code:
            return json.dumps({"status": "error", "error": "需要 code 参数"})
        # Deobfuscate patterns
        result = code
        # Unpack hex strings
        result = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), result)
        # Replace array indexing with readable names
        result = re.sub(r'\[(\d+)\]', lambda m: f'[{m.group(1)}]', result)
        return json.dumps({"status": "ok", "deobfuscated": result[:10000]})

    def close(self) -> None:
        pass
