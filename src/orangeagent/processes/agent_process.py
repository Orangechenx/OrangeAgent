"""Agent process entry point.

Each agent runs in its own OS process, communicating with the bus server
via HttpMessageBus (HTTP POST for publish, WebSocket for receive).

Usage:
    python -m orangeagent.processes.agent_process main_agent --server-url http://127.0.0.1:8720
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from pathlib import Path
from typing import Any

import structlog

from orangeagent.bus.http_client import HttpMessageBus
from orangeagent.config import settings

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SHUTDOWN_TIMEOUT = 3.0  # 等待 think() 完成的最长时间


async def run_agent(agent_type: str, server_url: str) -> None:
    """Create and run a single agent, blocking until SIGTERM/SIGINT."""
    bus = HttpMessageBus(server_url=server_url, agent_id=agent_type)
    await bus.initialize()

    agent = _create_agent(agent_type, bus)
    await agent.start()

    logger.info("agent_process_ready", agent_type=agent_type)

    # Block until shutdown signal
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("agent_signal_received", agent_type=agent_type)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (ValueError, RuntimeError) as exc:
            logger.warning("signal_handler_failed", signal=sig.name, error=str(exc))

    await stop_event.wait()

    logger.info("agent_process_shutting_down", agent_type=agent_type)
    try:
        await asyncio.wait_for(agent.stop(), timeout=_SHUTDOWN_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("agent_stop_timeout", agent_type=agent_type)
    await bus.close()


def _create_agent(agent_type: str, bus: HttpMessageBus) -> Any:
    """Factory: create the right Agent subclass for the given type."""
    prompts_dir = Path(settings.prompts_dir)
    agent_md_path = _PROJECT_ROOT / "AGENT.md"

    if agent_type == "main_agent":
        from orangeagent.agents.main_agent import MainAgent

        return MainAgent(
            bus=bus,
            model=settings.litellm_model,
            agent_md_path=agent_md_path,
            prompts_dir=prompts_dir,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

    if agent_type == "trace_agent":
        from orangeagent.agents.trace_agent import TraceAgent

        return TraceAgent(
            bus=bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            trace_files=settings.trace_files or None,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

    if agent_type == "ida_jadx_agent":
        from orangeagent.agents.ida_jadx_agent import IdaJadxAgent

        return IdaJadxAgent(
            bus=bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            jadx_host=settings.jadx_host,
            jadx_port=settings.jadx_port,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

    if agent_type == "frida_agent":
        from orangeagent.agents.frida_agent import FridaAgent

        return FridaAgent(
            bus=bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

    if agent_type == "network_agent":
        from orangeagent.agents.network_agent import NetworkAgent

        return NetworkAgent(
            bus=bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

    if agent_type == "apktool_agent":
        from orangeagent.agents.apktool_agent import ApktoolAgent
        return ApktoolAgent(bus=bus, model=settings.litellm_model, prompts_dir=prompts_dir,
                             verify_enabled=settings.verify_enabled, verify_max_retries=settings.verify_max_retries)

    if agent_type == "js_reverse_agent":
        from orangeagent.agents.js_reverse_agent import JsReverseAgent
        return JsReverseAgent(bus=bus, model=settings.litellm_model, prompts_dir=prompts_dir,
                              verify_enabled=settings.verify_enabled, verify_max_retries=settings.verify_max_retries)

    if agent_type == "ida_agent":
        from orangeagent.agents.ida_agent import IdaAgent
        return IdaAgent(bus=bus, model=settings.litellm_model, prompts_dir=prompts_dir,
                        verify_enabled=settings.verify_enabled, verify_max_retries=settings.verify_max_retries)

    if agent_type == "unidbg_agent":
        from orangeagent.agents.unidbg_agent import UnidbgAgent
        return UnidbgAgent(bus=bus, model=settings.litellm_model, prompts_dir=prompts_dir,
                           verify_enabled=settings.verify_enabled, verify_max_retries=settings.verify_max_retries)

    raise ValueError(f"Unknown agent type: {agent_type}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an OrangeAgent agent process")
    parser.add_argument(
        "agent_type",
        choices=["main_agent", "trace_agent", "ida_jadx_agent", "frida_agent",
             "network_agent", "apktool_agent", "js_reverse_agent", "ida_agent",
             "unidbg_agent"],
        help="Which agent to run",
    )
    parser.add_argument(
        "--server-url",
        required=True,
        help="Bus server URL, e.g. http://127.0.0.1:8720",
    )
    args = parser.parse_args()
    asyncio.run(run_agent(args.agent_type, args.server_url))


if __name__ == "__main__":
    main()
