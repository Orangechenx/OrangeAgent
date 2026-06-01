import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import typer
import structlog

from duckagent.bus import Message, MessageBus
from duckagent.agents.main_agent import MainAgent
from duckagent.agents.trace_agent import TraceAgent
from duckagent.config import settings

logger = structlog.get_logger()
app = typer.Typer(name="duck", help="DuckAgent - Android 逆向 Multi-Agent 系统")


@asynccontextmanager
async def get_bus():
    bus = MessageBus(db_path=settings.db_path)
    await bus.initialize()
    try:
        yield bus
    finally:
        await bus.close()


def format_message(msg: Message) -> str:
    ts = msg.timestamp.strftime("%H:%M") if isinstance(msg.timestamp, datetime) else str(msg.timestamp)[:5]
    target = msg.to_agent or "all"
    if target == "human":
        target = "you"
    return f"[{ts}] {msg.from_agent} → {target}: {msg.content}"


@app.command()
def run():
    """启动系统，进入交互模式"""
    asyncio.run(_run_interactive())


@app.command()
def log(
    from_agent: str = typer.Option(None, "--from", help="按发送者过滤"),
    limit: int = typer.Option(50, "--limit", help="消息数量限制"),
    msg_type: str = typer.Option(None, "--type", help="按消息类型过滤"),
):
    """查看消息历史"""
    asyncio.run(_show_log(from_agent, limit, msg_type))


@app.command()
def send(message: str):
    """发送消息给主 Agent（非交互模式）"""
    asyncio.run(_send_message(message))


async def _show_log(from_agent: str | None, limit: int, msg_type: str | None):
    async with get_bus() as bus:
        history = await bus.get_history(
            limit=limit, from_agent=from_agent, msg_type=msg_type
        )
        if not history:
            typer.echo("没有消息")
            return
        for msg in history:
            typer.echo(format_message(msg))


async def _send_message(content: str):
    async with get_bus() as bus:
        msg = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content=content,
            evidence=[],
            confidence="high",
        )
        await bus.publish(msg)
        typer.echo(f"已发送: {content}")


async def _run_interactive():
    typer.echo("DuckAgent 启动中...")

    bus = MessageBus(db_path=settings.db_path)
    await bus.initialize()

    prompts_dir = Path(settings.prompts_dir)
    agent_md_path = Path("AGENT.md")

    main_agent = MainAgent(
        bus=bus,
        model=settings.litellm_model,
        agent_md_path=agent_md_path,
        prompts_dir=prompts_dir,
        verify_enabled=settings.verify_enabled,
        verify_max_retries=settings.verify_max_retries,
    )

    trace_agent = TraceAgent(
        bus=bus,
        model=settings.litellm_model,
        prompts_dir=prompts_dir,
        verify_enabled=settings.verify_enabled,
        verify_max_retries=settings.verify_max_retries,
    )

    await main_agent.start()
    await trace_agent.start()

    human_queue = bus.subscribe("human")

    typer.echo("系统就绪。直接输入发送消息给主 Agent，Ctrl+C 退出。\n")

    display_task = asyncio.create_task(_display_messages(human_queue))

    try:
        await _input_loop(bus)
    except (KeyboardInterrupt, EOFError):
        typer.echo("\n正在停止...")
    finally:
        display_task.cancel()
        await main_agent.stop()
        await trace_agent.stop()
        await bus.close()
        typer.echo("已停止。")


async def _display_messages(queue: asyncio.Queue):
    while True:
        msg = await queue.get()
        typer.echo(f"\n{format_message(msg)}")
        typer.echo("> ", nl=False)


async def _input_loop(bus: MessageBus):
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("> "))
        except EOFError:
            break

        line = line.strip()
        if not line:
            continue

        msg = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content=line,
            evidence=[],
            confidence="high",
        )
        await bus.publish(msg)
