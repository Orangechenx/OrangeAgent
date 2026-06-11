"""Apktool tool executor — APK 解包/重打包/签名包装。"""

from __future__ import annotations

import json
import subprocess
import shutil
from pathlib import Path
from typing import Any


class ApkToolExecutor:
    """Executes APK analysis and repackaging via apktool CLI."""

    def __init__(self) -> None:
        self._apktool = shutil.which("apktool") or shutil.which("java")

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "apktool_decode":
                return self._decode(arguments)
            if name == "apktool_build":
                return self._build(arguments)
            if name == "apktool_manifest":
                return self._manifest(arguments)
            if name == "apktool_search_string":
                return self._search_string(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _decode(self, args: dict[str, Any]) -> str:
        apk = args.get("apk_path", "")
        if not apk:
            return json.dumps({"status": "error", "error": "需要 apk_path"}, ensure_ascii=False)
        output = Path(apk).stem + "_decoded"
        cmd = ["apktool", "d", "-f", "-o", output, apk]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return json.dumps({"status": "error", "error": proc.stderr[:2000]}, ensure_ascii=False)
        return json.dumps({"status": "ok", "output_dir": output, "files": len(list(Path(output).rglob("*")))})

    def _build(self, args: dict[str, Any]) -> str:
        dir_path = args.get("dir", "")
        output = args.get("output", "dist.apk")
        if not dir_path:
            return json.dumps({"status": "error", "error": "需要 dir"}, ensure_ascii=False)
        cmd = ["apktool", "b", "-o", output, dir_path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return json.dumps({"status": "error", "error": proc.stderr[:2000]}, ensure_ascii=False)
        return json.dumps({"status": "ok", "output": output})

    def _manifest(self, args: dict[str, Any]) -> str:
        decoded = args.get("decoded_dir", "")
        manifest_path = Path(decoded) / "AndroidManifest.xml"
        if not manifest_path.exists():
            return json.dumps({"status": "error", "error": f"AndroidManifest.xml not found in {decoded}"})
        text = manifest_path.read_text()
        return json.dumps({"status": "ok", "content": text[:5000]})

    def _search_string(self, args: dict[str, Any]) -> str:
        decoded = args.get("decoded_dir", "")
        keyword = args.get("keyword", "")
        if not decoded or not keyword:
            return json.dumps({"status": "error", "error": "需要 decoded_dir 和 keyword"})
        results = []
        for smali in Path(decoded).rglob("*.smali"):
            if keyword in smali.read_text():
                rel = smali.relative_to(decoded)
                results.append(str(rel))
        return json.dumps({"status": "ok", "matches": results[:50], "count": len(results)})

    def close(self) -> None:
        pass
