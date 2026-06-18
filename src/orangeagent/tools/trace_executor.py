from __future__ import annotations

import json
import re
import select
import subprocess
from pathlib import Path
from typing import Any

# daemon 单行响应最长等待秒数：超过即判定卡死，避免 readline 永久阻塞整个进程
_DAEMON_READ_TIMEOUT = 30.0


class LocalTraceToolExecutor:
    """Executes trace_search, trace_context, trace_cross_ref via ak_search daemon."""

    def __init__(self, trace_files: dict[str, Path], repo_root: Path | None = None) -> None:
        self._file_paths = {k: v.resolve() for k, v in trace_files.items() if v.exists()}
        if not self._file_paths:
            raise FileNotFoundError(f"No trace files found: {trace_files}")
        self._repo_root = repo_root or self._discover_repo_root()
        self._search_bin = self._repo_root / "tools" / "search" / "ak_search"
        self._daemons: dict[str, subprocess.Popen[str]] = {}

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "trace_search":
                return self._trace_search(arguments)
            if name == "trace_context":
                return self._trace_context(arguments)
            if name == "trace_cross_ref":
                return self._trace_cross_ref(arguments)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
        return json.dumps({"status": "error", "error": f"Unknown tool: {name}"})

    def close(self) -> None:
        for key in list(self._daemons):
            self._close_daemon(key)

    def _discover_repo_root(self) -> Path:
        candidates = [Path.cwd(), Path(__file__).resolve().parents[3]]
        for c in candidates:
            if (c / "tools" / "search").is_dir():
                return c
        return Path.cwd()

    def _ensure_bin(self) -> None:
        if self._search_bin.exists():
            return
        search_dir = self._search_bin.parent
        if not search_dir.is_dir():
            raise FileNotFoundError(f"Search tool directory not found: {search_dir}")
        subprocess.run(["make"], cwd=search_dir, check=True, capture_output=True, text=True)

    def _readline_timeout(self, daemon: subprocess.Popen[str], file_key: str) -> str:
        """带超时的 readline：daemon 卡死（崩溃未关 stdout / IO 阻塞）时不再永久挂起。

        daemon 协议为逐行 JSON 且每行写完即 flush，POSIX pipe 支持 select，
        因此用 select 轮询 fd 可读性即可，不会出现半行误判。
        超时则强制关闭 daemon 并抛错，由上层走重试或返回错误。
        """
        stdout = daemon.stdout
        assert stdout is not None
        ready, _, _ = select.select([stdout], [], [], _DAEMON_READ_TIMEOUT)
        if not ready:
            self._close_daemon(file_key)
            raise TimeoutError(
                f"Daemon ({file_key}) 在 {_DAEMON_READ_TIMEOUT:.0f}s 内无响应，已强制关闭"
            )
        return stdout.readline()

    def _close_daemon(self, file_key: str) -> None:
        daemon = self._daemons.pop(file_key, None)
        if daemon is None:
            return
        if daemon.poll() is None:
            try:
                if daemon.stdin:
                    daemon.stdin.write("quit\n")
                    daemon.stdin.flush()
            except Exception:
                pass
            try:
                daemon.wait(timeout=1)
            except subprocess.TimeoutExpired:
                daemon.terminate()
                try:
                    daemon.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    daemon.kill()

    def _ensure_daemon(self, file_key: str) -> subprocess.Popen[str]:
        existing = self._daemons.get(file_key)
        if existing is not None and existing.poll() is None:
            return existing

        self._close_daemon(file_key)
        self._ensure_bin()

        file_path = self._file_paths.get(file_key)
        if file_path is None:
            raise ValueError(f"Trace file '{file_key}' not available. Have: {', '.join(self._file_paths)}")

        cmd = [str(self._search_bin), "daemon", "--file", str(file_path)]
        if file_key in {"rw", "bl"}:
            cmd.append("--indexed-prefix")

        daemon = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, errors="replace",
        )
        if daemon.stdout is None:
            daemon.kill()
            raise RuntimeError(f"Daemon ({file_key}) has no stdout")

        # 启动握手同样加超时：daemon 启动后若卡住不写 ready 行，
        # 不能让 readline 永久阻塞（此时 daemon 尚未登记到 self._daemons）
        h_ready, _, _ = select.select([daemon.stdout], [], [], _DAEMON_READ_TIMEOUT)
        if not h_ready:
            daemon.kill()
            raise TimeoutError(
                f"Daemon ({file_key}) 启动 {_DAEMON_READ_TIMEOUT:.0f}s 内无握手响应"
            )
        ready_line = daemon.stdout.readline()
        if not ready_line:
            stderr = daemon.stderr.read() if daemon.stderr else ""
            daemon.wait(timeout=1)
            raise RuntimeError(f"Daemon ({file_key}) failed to start: {stderr.strip()}")

        ready = json.loads(ready_line)
        if ready.get("type") != "daemon_ready" or ready.get("status") != "ok":
            daemon.kill()
            raise RuntimeError(f"Daemon ({file_key}) refused: {ready}")

        self._daemons[file_key] = daemon
        return daemon

    def _daemon_request(self, file_key: str, command: str, *, max_chars: int = 30000, retry: bool = True) -> str:
        daemon = self._ensure_daemon(file_key)
        if daemon.stdin is None or daemon.stdout is None:
            self._close_daemon(file_key)
            raise RuntimeError(f"Daemon ({file_key}) pipes unavailable")

        try:
            daemon.stdin.write(command + "\n")
            daemon.stdin.flush()
        except (BrokenPipeError, OSError):
            self._close_daemon(file_key)
            if retry:
                return self._daemon_request(file_key, command, max_chars=max_chars, retry=False)
            raise

        parts: list[str] = []
        chars = 0
        truncated = False
        while True:
            line = self._readline_timeout(daemon, file_key)
            if not line:
                self._close_daemon(file_key)
                if retry:
                    return self._daemon_request(file_key, command, max_chars=max_chars, retry=False)
                raise RuntimeError("Daemon exited unexpectedly")
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("type") == "daemon_end":
                return json.dumps({
                    "status": "ok" if data.get("status") == "ok" else "error",
                    "stdout": "".join(parts),
                    "truncated": truncated,
                }, ensure_ascii=False)
            if chars + len(line) <= max_chars:
                parts.append(line)
                chars += len(line)
            else:
                truncated = True

    # --- trace_search ---

    def _trace_search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments["query"])
        if not query:
            raise ValueError("query must not be empty")
        file_key = str(arguments.get("file", "code"))
        if file_key not in self._file_paths:
            raise ValueError(f"file must be one of: {', '.join(sorted(self._file_paths))}")

        has_from = "from_line" in arguments
        has_before = "before_line" in arguments
        if has_from == has_before:
            raise ValueError("exactly one of from_line or before_line is required")

        limit = min(int(arguments["limit"]), 100)
        from_line = int(arguments.get("from_line", 0))
        before_line = int(arguments.get("before_line", 0))

        result = self._search_once(file_key, query, from_line=from_line, before_line=before_line, limit=limit)
        if not self._is_empty_success(result):
            return result

        for fallback in self._hex_fallbacks(query):
            fb_result = self._search_once(file_key, fallback, from_line=from_line, before_line=before_line, limit=limit)
            if self._has_matches(fb_result):
                return fb_result
        return result

    def _search_once(self, file_key: str, query: str, *, from_line: int, before_line: int, limit: int) -> str:
        query_hex = query.encode("utf-8").hex()
        return self._daemon_request(file_key, f"match\t{from_line}\t{before_line}\t{limit}\t{query_hex}")

    def _has_matches(self, result_json: str) -> bool:
        r = json.loads(result_json)
        return r.get("status") == "ok" and bool(str(r.get("stdout") or "").strip())

    def _is_empty_success(self, result_json: str) -> bool:
        r = json.loads(result_json)
        return r.get("status") == "ok" and not str(r.get("stdout") or "").strip()

    def _hex_fallbacks(self, query: str) -> list[str]:
        if not query.lower().startswith("0x"):
            return []
        hex_digits = query[2:]
        if not re.fullmatch(r"[0-9a-fA-F]+", hex_digits):
            return []
        fallbacks = [self._byte_reverse(hex_digits)]
        trimmed = hex_digits.lstrip("0")
        if trimmed and trimmed != hex_digits:
            fallbacks.append("0x" + trimmed)
            fallbacks.append(self._byte_reverse(trimmed))
        seen = {query.lower()}
        return [f for f in fallbacks if f.lower() not in seen and not seen.add(f.lower())]

    @staticmethod
    def _byte_reverse(hex_digits: str) -> str:
        padded = hex_digits if len(hex_digits) % 2 == 0 else "0" + hex_digits
        return "0x" + "".join(reversed([padded[i:i+2] for i in range(0, len(padded), 2)]))

    # --- trace_context ---

    def _trace_context(self, arguments: dict[str, Any]) -> str:
        file_key = str(arguments.get("file", "code"))
        if file_key not in self._file_paths:
            raise ValueError(f"file must be one of: {', '.join(sorted(self._file_paths))}")
        line = int(arguments["line"])
        before = min(int(arguments.get("before", 0)), 100)
        after = min(int(arguments.get("after", 0)), 100)
        return self._daemon_request(file_key, f"context\t{line}\t{before}\t{after}")

    # --- trace_cross_ref ---

    def _trace_cross_ref(self, arguments: dict[str, Any]) -> str:
        seq_id = str(arguments.get("seq_id", "")).strip().lower()
        if not seq_id or not re.fullmatch(r"[0-9a-f]+", seq_id):
            raise ValueError("seq_id must be a non-empty hex string (without 0x prefix)")

        seq_decimal = int(seq_id, 16)
        result: dict[str, Any] = {"status": "ok", "seq_id": seq_id}

        if "code" in self._file_paths:
            code_line = seq_decimal + 2
            code_result = json.loads(
                self._daemon_request("code", f"context\t{code_line}\t0\t0", max_chars=5000)
            )
            if code_result.get("status") == "ok" and code_result.get("stdout", "").strip():
                raw = code_result["stdout"].strip()
                try:
                    line_data = json.loads(raw.split("\n")[0])
                    result["code"] = {"line": code_line, "text": line_data.get("text", "")}
                except (json.JSONDecodeError, IndexError):
                    result["code"] = {"line": code_line, "text": raw}
            else:
                result["code"] = {"line": code_line, "text": None}

        if "rw" in self._file_paths:
            result["rw"] = self._seq_lookup("rw", seq_decimal)

        if "bl" in self._file_paths:
            result["bl"] = self._seq_lookup("bl", seq_decimal)

        return json.dumps(result, ensure_ascii=False)

    def _seq_lookup(self, file_key: str, seq_decimal: int) -> list[dict[str, Any]]:
        lookup_result = json.loads(
            self._daemon_request(file_key, f"seq_lookup\t{seq_decimal}\t10", max_chars=10000)
        )
        if lookup_result.get("status") != "ok":
            return []
        stdout = lookup_result.get("stdout", "")
        if not stdout.strip():
            return []

        records: list[dict[str, Any]] = []
        current_lines: list[str] = []
        current_line_no: int | None = None

        for json_line in stdout.strip().split("\n"):
            try:
                data = json.loads(json_line)
            except json.JSONDecodeError:
                continue
            if data.get("type") != "seq_match":
                continue
            text = data.get("text", "")
            if data.get("target", False):
                if current_lines and current_line_no is not None:
                    records.append({"line": current_line_no, "raw": "\n".join(current_lines)})
                current_lines = [text]
                current_line_no = data.get("line")
            else:
                current_lines.append(text)

        if current_lines and current_line_no is not None:
            records.append({"line": current_line_no, "raw": "\n".join(current_lines)})

        return records
