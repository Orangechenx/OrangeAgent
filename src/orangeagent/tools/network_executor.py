"""Network tool executor — HTTP 请求与流量分析。

纯 Python 实现，无外部依赖。
"""

from __future__ import annotations

import json
import re
from typing import Any


class NetworkToolExecutor:
    """Executes network analysis tools via httpx."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=15.0, verify=False)
        return self._client

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "network_make_request":
                return self._make_request(arguments)
            if name == "network_analyze_params":
                return self._analyze_params(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _make_request(self, args: dict[str, Any]) -> str:
        url = args.get("url", "")
        if not url:
            return json.dumps({"status": "error", "error": "url 是必需的"}, ensure_ascii=False)

        method = args.get("method", "GET").upper()
        headers = {}
        if args.get("headers"):
            try:
                headers = json.loads(args["headers"])
            except json.JSONDecodeError:
                pass

        body = args.get("body")
        client = self._get_client()

        response = client.request(method, url, headers=headers, content=body)
        content = response.text
        return json.dumps({
            "status": "ok",
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content_length": len(content),
            "content_preview": content[:3000],
        }, ensure_ascii=False)

    @staticmethod
    def _analyze_params(args: dict[str, Any]) -> str:
        url = args.get("url", "")
        body = args.get("body", "")

        findings = []

        # 提取 URL 参数
        if "?" in url:
            query = url.split("?", 1)[1]
            params = query.split("&")
            for param in params:
                if "=" in param:
                    key, value = param.split("=", 1)
                    findings.append({
                        "param": key,
                        "location": "url_query",
                        "value_preview": value[:50],
                        "likely_signature": _is_likely_signature(key, value),
                    })

        # 解析 JSON body
        if body:
            try:
                data = json.loads(body)
                for key, value in (data if isinstance(data, dict) else {}).items():
                    findings.append({
                        "param": key,
                        "location": "body",
                        "value_preview": str(value)[:50],
                        "likely_signature": _is_likely_signature(key, str(value)),
                    })
            except json.JSONDecodeError:
                pass

        return json.dumps({
            "status": "ok",
            "total_params": len(findings),
            "findings": findings,
            "suspected_signatures": [
                f for f in findings if f["likely_signature"]
            ],
        }, ensure_ascii=False)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None


_SIGNATURE_PARAM_PATTERNS = re.compile(
    r"(sign|sig|token|auth|md5|sha|hash|hmac|encrypt|secret|key)"
    r"|^[a-f0-9]{32,}$|^[A-Za-z0-9+/]{20,}={0,2}$",
    re.IGNORECASE,
)


def _is_likely_signature(key: str, value: str) -> bool:
    """判断参数是否可能是签名或令牌。"""
    if _SIGNATURE_PARAM_PATTERNS.search(key):
        return True
    # 32 位 hex（MD5）
    if re.fullmatch(r"[a-f0-9]{32}", value, re.IGNORECASE):
        return True
    # 40 位 hex（SHA1）
    if re.fullmatch(r"[a-f0-9]{40}", value, re.IGNORECASE):
        return True
    # Base64 疑似签名
    if re.fullmatch(r"[A-Za-z0-9+/]{20,}={0,2}", value):
        return True
    return False
