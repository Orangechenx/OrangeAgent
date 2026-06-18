"""Frida tool executor — uses frida Python bindings for dynamic analysis.

当 frida 不可用时，工具会返回清晰的引导信息，不会崩溃。
"""

from __future__ import annotations

import json
import re
from typing import Any


# Frida 脚本模板
_ENUMERATE_CLASSES_SCRIPT = """
Java.perform(function() {
    var classes = [];
    Java.enumerateLoadedClasses({
        onMatch: function(className) { classes.push(className); },
        onComplete: function() { send(JSON.stringify(classes)); }
    });
});
"""

_HOOK_METHOD_SCRIPT = """
Java.perform(function() {
    var targetClass = Java.use('{class_name}');
    targetClass['{method_name}'].implementation = function() {{
        var args = Array.prototype.slice.call(arguments);
        send(JSON.stringify({{
            "method": "{class_name}.{method_name}",
            "args": args.map(function(a) {{ return String(a); }}),
            "stacktrace": Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new())
        }}));
        return this['{method_name}'].apply(this, arguments);
    }};
});
"""


class FridaToolExecutor:
    """Executes Frida dynamic analysis via frida Python bindings.

    工具执行时检查 frida 是否可用，不可用时返回清晰提示。
    """

    def __init__(self) -> None:
        self._frida = None
        self._session = None
        self._device = None
        self._available = False
        self._init_frida()

    def _init_frida(self) -> None:
        try:
            import frida
            self._frida = frida
            self._available = True
        except ImportError:
            self._available = False

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "frida_list_devices":
                return self._list_devices()
            if name == "frida_list_processes":
                return self._list_processes(arguments)
            if name == "frida_enumerate_classes":
                return self._enumerate_classes(arguments)
            if name == "frida_hook_method":
                return self._hook_method(arguments)
            if name == "frida_generate_hook_script":
                return self._generate_hook_script(arguments)
            if name == "frida_generate_enumerate_script":
                return self._generate_enumerate_script()
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _ensure_frida(self) -> None:
        if not self._available:
            raise RuntimeError(
                "frida Python 包未安装。安装: pip install frida-tools\n"
                "如果已安装，请确认 USB 设备已连接且 frida-server 正在运行。"
            )

    def _get_device(self, device_id: str | None = None) -> Any:
        self._ensure_frida()
        if device_id:
            return self._frida.get_device(device_id)
        return self._frida.get_usb_device(timeout=5)

    @staticmethod
    def _resolve_target(pid: Any) -> Any:
        """归一化 attach 目标：纯数字按 pid（int）处理，否则按包名（str）。

        LLM 可能把 pid 传成 JSON number（int），旧代码直接 pid.isdigit() 会抛
        AttributeError。这里统一转 str 再判定，兼容 int / str 两种输入。
        """
        s = str(pid).strip()
        return int(s) if s.isdigit() else s

    def _list_devices(self) -> str:
        self._ensure_frida()
        devices = self._frida.enumerate_devices()
        lines = [f"- {d.id} ({d.name}) [{d.type}]" for d in devices]
        return json.dumps({
            "status": "ok",
            "devices": lines,
            "count": len(lines),
        }, ensure_ascii=False)

    def _list_processes(self, args: dict[str, Any]) -> str:
        device = self._get_device(args.get("device_id"))
        processes = device.enumerate_processes()
        lines = [f"- {p.pid}: {p.name}" for p in processes]
        return json.dumps({
            "status": "ok",
            "processes": lines[:100],  # 限制 100 个
            "count": min(len(lines), 100),
        }, ensure_ascii=False)

    def _enumerate_classes(self, args: dict[str, Any]) -> str:
        device = self._get_device(args.get("device_id"))
        target = self._resolve_target(args.get("pid", ""))
        session = device.attach(target)
        try:
            script = session.create_script(_ENUMERATE_CLASSES_SCRIPT)
            result = []

            def on_message(msg: dict, data: bytes | None) -> None:
                if msg.get("type") == "send":
                    result.append(msg.get("payload", ""))

            script.on("message", on_message)
            script.load()
            import time
            time.sleep(1)
            session.detach()
            return json.dumps({
                "status": "ok",
                "classes": result[0] if result else [],
                "count": len(result[0]) if result else 0,
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        finally:
            try:
                session.detach()
            except Exception:
                pass

    def _hook_method(self, args: dict[str, Any]) -> str:
        """注入 Hook 并返回一次调用的结果。"""
        device = self._get_device(args.get("device_id"))
        class_name = args.get("class", "")
        method_name = args.get("method", "")

        if not class_name or not method_name:
            return json.dumps({"status": "error", "error": "需要 class 和 method 参数"})

        script_body = _HOOK_METHOD_SCRIPT.format(
            class_name=class_name,
            method_name=method_name,
        )
        session = device.attach(self._resolve_target(args.get("pid", "")))
        try:
            script = session.create_script(script_body)
            results = []

            def on_message(msg: dict, data: bytes | None) -> None:
                if msg.get("type") == "send":
                    results.append(msg.get("payload", ""))

            script.on("message", on_message)
            script.load()
            import time
            time.sleep(2)
            session.detach()
            return json.dumps({
                "status": "ok" if results else "no_calls",
                "hits": results,
                "count": len(results),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        finally:
            try:
                session.detach()
            except Exception:
                pass

    @staticmethod
    def _generate_hook_script(args: dict[str, Any]) -> str:
        """生成 Hook 脚本内容（无需设备连接）。"""
        class_name = args.get("class", "com.example.TargetClass")
        method_name = args.get("method", "targetMethod")
        overload = args.get("overload", "")

        script = _HOOK_METHOD_SCRIPT.format(
            class_name=class_name,
            method_name=method_name,
        )
        script += "\n// 注意: 替换为实际重载签名后取消注释\n"
        script += f"// targetClass['{method_name}'].overload('{overload or 'int'}').implementation = function(){{...}}"
        return json.dumps({
            "status": "ok",
            "script": script,
            "usage": f"保存为 .js 文件后用 frida -U -l script.js <package_name> 运行",
        }, ensure_ascii=False)

    @staticmethod
    def _generate_enumerate_script() -> str:
        script = _ENUMERATE_CLASSES_SCRIPT
        script += "\n\n// 枚举指定包名的类:\n"
        script += "// Java.enumerateLoadedClasses('com.example.*', callback);"
        return json.dumps({
            "status": "ok",
            "script": script,
            "usage": "保存为 .js 文件后用 frida -U -l script.js <package_name> 运行",
        }, ensure_ascii=False)

    def close(self) -> None:
        if self._session:
            try:
                self._session.detach()
            except Exception:
                pass
            self._session = None
