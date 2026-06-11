"""Unidbg tool executor — Native SO 模拟执行与算法复现。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


class UnidbgToolExecutor:
    """Executes unidbg for native SO simulation."""

    def __init__(self) -> None:
        self._java = shutil.which("java")
        self._unidbg_dir = Path.home() / "AndroidreverseEngineering" / "unidbg-0.9.9"
        self._available = self._java is not None and self._unidbg_dir.exists()

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "unidbg_run":
                return self._run(arguments)
            if name == "unidbg_generate_template":
                return self._generate_template(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def _run(self, args: dict[str, Any]) -> str:
        class_path = args.get("class", "")
        so_path = args.get("so", "")
        method = args.get("method", "")
        args_list = args.get("args", "")

        if not self._available:
            return json.dumps({
                "status": "error",
                "error": "unidbg 环境未就绪（需要 Java + unidbg-0.9.9）",
                "setup": "cd ~/AndroidreverseEngineering/unidbg-0.9.9 && mvn clean package -DskipTests",
            })

        if not class_path:
            return json.dumps({"status": "error", "error": "需要 class (Java 类路径)"})

        cmd = [
            self._java, "-jar",
            str(self._unidbg_dir / "unidbg-android" / "target" / "unidbg-android-0.9.9.jar"),
            class_path,
        ]
        if method:
            cmd.extend(["--method", method])
        if args_list:
            cmd.extend(["--args", args_list])
        if so_path:
            cmd.extend(["--so", so_path])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return json.dumps({
                "status": "ok",
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:1000],
            }, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"status": "error", "error": "unidbg 执行超时"})

    @staticmethod
    def _generate_template(args: dict[str, Any]) -> str:
        class_name = args.get("class", "com.example.SignUtil")
        method_name = args.get("method", "sign")
        so_name = args.get("so", "libexample.so")

        template = f"""package com.example;

import com.github.unidbg.AndroidEmulator;
import com.github.unidbg.Module;
import com.github.unidbg.linux.android.AndroidEmulatorBuilder;
import com.github.unidbg.linux.android.AndroidResolver;
import com.github.unidbg.linux.android.dvm.*;
import com.github.unidbg.linux.android.dvm.array.ByteArray;
import com.github.unidbg.memory.Memory;

import java.io.File;
import java.nio.charset.StandardCharsets;

public class {class_name.split('.')[-1]} extends AbstractJni {{

    private final AndroidEmulator emulator;
    private final Module module;
    private final VM vm;

    public {class_name.split('.')[-1]}() {{
        emulator = AndroidEmulatorBuilder.for32Bit().setProcessName("com.example").build();
        Memory memory = emulator.getMemory();
        memory.setLibraryResolver(new AndroidResolver(23));

        vm = emulator.createDalvikVM();
        vm.setJni(this);
        vm.setVerbose(true);

        DalvikModule dm = vm.loadLibrary(new File("{so_name}"), false);
        dm.callJNI_OnLoad(emulator);
        module = dm.getModule();
    }}

    public String {method_name}(String input) {{
        // 调用 Native 方法
        DvmObject<?> result = vm.callStaticJniMethod(emulator, "{class_name}.{method_name}",
                vm.addLocalObject(new StringObject(vm, input)));
        return result.getValue().toString();
    }}

    public static void main(String[] args) {{
        {class_name.split('.')[-1]} driver = new {class_name.split('.')[-1]}();
        String result = driver.{method_name}(args.length > 0 ? args[0] : "test_input");
        System.out.println("Result: " + result);
    }}
}}
"""
        return json.dumps({
            "status": "ok",
            "template": template,
            "usage": f"将此文件放到 unidbg-android 项目中，替换包名和 SO 路径后编译运行",
        }, ensure_ascii=False)

    def close(self) -> None:
        pass
