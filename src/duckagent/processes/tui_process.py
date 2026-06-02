"""TUI process entry point.

The TUI runs as an observer — it sees ALL messages flowing through the bus
and renders them. In HTTP mode it does NOT create agent instances; those
run in separate processes.

Usage:
    python -m duckagent.processes.tui_process --server-url http://127.0.0.1:8720
"""

from __future__ import annotations

import argparse
import asyncio


async def run_tui(server_url: str) -> None:
    """Launch the Textual TUI with an HttpMessageBus in observer mode."""
    from duckagent.bus.http_client import HttpMessageBus
    from duckagent.cli.tui.app import DuckApp

    bus = HttpMessageBus(server_url=server_url, agent_id=None)  # observer mode
    app = DuckApp(bus=bus, http_mode=True)
    await app.run_async()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DuckAgent TUI")
    parser.add_argument(
        "--server-url",
        required=True,
        help="Bus server URL, e.g. http://127.0.0.1:8720",
    )
    args = parser.parse_args()
    asyncio.run(run_tui(args.server_url))


if __name__ == "__main__":
    main()
