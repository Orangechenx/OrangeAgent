from __future__ import annotations

import json
import urllib.request
import urllib.parse
from typing import Any


class JadxToolExecutor:
    """Executes JADX static analysis tools via JADX Java plugin HTTP API.

    The JADX GUI must be running with the AI MCP Plugin enabled
    (default: http://127.0.0.1:8650).
    """

    def __init__(
        self,
        jadx_host: str = "127.0.0.1",
        jadx_port: int = 8650,
        timeout: int = 60,
    ) -> None:
        self._base_url = f"http://{jadx_host}:{jadx_port}"
        self._timeout = timeout

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "jadx_search_classes_by_keyword":
                return self._search_classes_by_keyword(arguments)
            if name == "jadx_get_class_source":
                return self._get_class_source(arguments)
            if name == "jadx_get_method_by_name":
                return self._get_method_by_name(arguments)
            if name == "jadx_get_xrefs_to_class":
                return self._get_xrefs_to_class(arguments)
            if name == "jadx_get_xrefs_to_method":
                return self._get_xrefs_to_method(arguments)
            if name == "jadx_get_methods_of_class":
                return self._get_methods_of_class(arguments)
            if name == "jadx_get_fields_of_class":
                return self._get_fields_of_class(arguments)
            if name == "jadx_get_android_manifest":
                return self._get_android_manifest(arguments)
            if name == "jadx_get_smali_of_class":
                return self._get_smali_of_class(arguments)
            if name == "jadx_get_strings":
                return self._get_strings(arguments)
            if name == "jadx_get_main_activity_class":
                return self._get_main_activity_class(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"}, ensure_ascii=False)

    def close(self) -> None:
        pass  # No cleanup needed for HTTP-based executor

    def _get(self, endpoint: str, params: dict[str, str] | None = None) -> str:
        """Make a synchronous GET request to the JADX plugin."""
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        if params:
            # Filter out None/empty values
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            # Try JSON parse, fall back to text
            try:
                parsed = json.loads(body)
                return json.dumps(parsed, ensure_ascii=False)
            except json.JSONDecodeError:
                return json.dumps({"response": body}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

    def _search_classes_by_keyword(self, args: dict[str, Any]) -> str:
        search_term = str(args["search_term"])
        return self._get("search-classes-by-keyword", {
            "search_term": search_term,
            "package": str(args.get("package", "")),
            "search_in": str(args.get("search_in", "code")),
            "offset": str(args.get("offset", 0)),
            "count": str(args.get("count", 20)),
        })

    def _get_class_source(self, args: dict[str, Any]) -> str:
        return self._get("class-source", {
            "class_name": str(args["class_name"])
        })

    def _get_method_by_name(self, args: dict[str, Any]) -> str:
        return self._get("method-by-name", {
            "class_name": str(args["class_name"]),
            "method_name": str(args["method_name"]),
        })

    def _get_xrefs_to_class(self, args: dict[str, Any]) -> str:
        return self._get("xrefs-to-class", {
            "class_name": str(args["class_name"]),
            "offset": str(args.get("offset", 0)),
            "count": str(args.get("count", 20)),
        })

    def _get_xrefs_to_method(self, args: dict[str, Any]) -> str:
        return self._get("xrefs-to-method", {
            "class_name": str(args["class_name"]),
            "method_name": str(args["method_name"]),
            "offset": str(args.get("offset", 0)),
            "count": str(args.get("count", 20)),
        })

    def _get_methods_of_class(self, args: dict[str, Any]) -> str:
        return self._get("methods-of-class", {
            "class_name": str(args["class_name"])
        })

    def _get_fields_of_class(self, args: dict[str, Any]) -> str:
        return self._get("fields-of-class", {
            "class_name": str(args["class_name"])
        })

    def _get_android_manifest(self, args: dict[str, Any]) -> str:
        return self._get("manifest")

    def _get_smali_of_class(self, args: dict[str, Any]) -> str:
        return self._get("smali-of-class", {
            "class_name": str(args["class_name"])
        })

    def _get_strings(self, args: dict[str, Any]) -> str:
        return self._get("strings", {
            "offset": str(args.get("offset", 0)),
            "count": str(args.get("count", 0)),
        })

    def _get_main_activity_class(self, args: dict[str, Any]) -> str:
        return self._get("main-activity")
