"""IDA Pro tool executor — wraps ida-pro-mcp for native static analysis."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class IdaToolExecutor:
    """Executes IDA Pro analysis via ida-pro-mcp CLI."""

    def __init__(self) -> None:
        self._ida_cmd = shutil.which("ida-pro-mcp")

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "ida_analyze_function":
                return self._analyze_function(arguments)
            if name == "ida_decompile":
                return self._decompile(arguments)
            if name == "ida_list_functions":
                return self._list_functions(arguments)
            if name == "ida_search_xrefs":
                return self._search_xrefs(arguments)
            if name == "ida_get_strings":
                return self._get_strings(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _run_ida(self, args: list[str]) -> str:
        if not self._ida_cmd:
            return json.dumps({"status": "error", "error": "ida-pro-mcp 未安装"})
        try:
            result = subprocess.run([self._ida_cmd] + args, capture_output=True, text=True, timeout=60)
            return result.stdout or result.stderr
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "IDA 命令超时"})

    def _analyze_function(self, args: dict[str, Any]) -> str:
        return self._run_ida(["--function", args.get("address", args.get("name", ""))])

    def _decompile(self, args: dict[str, Any]) -> str:
        return self._run_ida(["--decompile", args.get("address", "")])

    def _list_functions(self, args: dict[str, Any]) -> str:
        binary = args.get("binary", "")
        cmd = ["--list-functions"]
        if binary:
            cmd.extend(["--binary", binary])
        return self._run_ida(cmd)

    def _search_xrefs(self, args: dict[str, Any]) -> str:
        return self._run_ida(["--xrefs", args.get("address", "")])

    def _get_strings(self, args: dict[str, Any]) -> str:
        return self._run_ida(["--strings"])

    def close(self) -> None:
        pass
