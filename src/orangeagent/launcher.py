"""Multi-process launcher.

Spawns the bus server, agent processes, and TUI using subprocess.Popen.
The TUI is the foreground process — when it exits, everything is torn down.

Usage:
    uv run orange launch --port 8720
"""

from __future__ import annotations

import subprocess
import sys
import time

import httpx

_DEFAULT_PORT = 8720
_DEFAULT_AGENTS = [
    "main_agent", "trace_agent", "ida_jadx_agent", "frida_agent",
    "network_agent", "apktool_agent", "js_reverse_agent", "ida_agent",
    "unidbg_agent",
]
_HEALTH_POLL_INTERVAL = 0.5
_HEALTH_TIMEOUT = 10.0
_AGENT_HEALTH_TIMEOUT = 5.0


class Launcher:
    """Manages the lifecycle of all OrangeAgent processes."""

    def __init__(
        self,
        server_port: int = _DEFAULT_PORT,
        agents: list[str] | None = None,
    ) -> None:
        self._server_port = server_port
        self._agents = agents or _DEFAULT_AGENTS
        self._procs: list[tuple[str, subprocess.Popen[bytes]]] = []

    def start(self) -> None:
        """Start all processes. Blocks on the TUI; tears down on exit."""
        server_url = f"http://127.0.0.1:{self._server_port}"
        python = sys.executable

        # 1. Start bus server
        server = subprocess.Popen(
            [
                python, "-m", "uvicorn", "orangeagent.server.app:app",
                "--host", "127.0.0.1", "--port", str(self._server_port),
                "--log-level", "warning",
            ],
        )
        self._procs.append(("server", server))

        # 2. Wait for server readiness
        self._wait_for_server(server_url)

        # 3. Start agent processes with health check
        for agent_type in self._agents:
            proc = subprocess.Popen(
                [
                    python, "-m", "orangeagent.processes.agent_process",
                    agent_type,
                    "--server-url", server_url,
                ],
            )
            self._procs.append((agent_type, proc))

        # 4. Start TUI (foreground — blocks until user exits)
        tui = subprocess.Popen(
            [
                python, "-m", "orangeagent.processes.tui_process",
                "--server-url", server_url,
            ],
        )
        self._procs.append(("tui", tui))

        # 5. Wait for TUI to exit
        tui.wait()

        # 6. Shutdown everything
        self.shutdown()

    def shutdown(self) -> None:
        """Terminate all child processes gracefully, then forcefully."""
        for name, proc in reversed(self._procs):
            if proc.poll() is None:
                proc.terminate()

        # Give them time to exit gracefully
        deadline = time.monotonic() + 5.0
        for name, proc in self._procs:
            timeout = max(0.0, deadline - time.monotonic())
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass

    def _wait_for_server(self, server_url: str) -> None:
        """Poll /api/v1/health until the server responds or timeout."""
        deadline = time.monotonic() + _HEALTH_TIMEOUT
        while time.monotonic() < deadline:
            # Check if server process died
            server_name, server_proc = self._procs[0]
            if server_proc.poll() is not None:
                raise RuntimeError(
                    f"Bus server exited early with code {server_proc.returncode}"
                )
            try:
                resp = httpx.get(
                    f"{server_url}/api/v1/health",
                    timeout=1.0,
                )
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(_HEALTH_POLL_INTERVAL)

        raise TimeoutError(
            f"Bus server did not become healthy within {_HEALTH_TIMEOUT}s"
        )
