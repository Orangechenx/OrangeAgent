import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import typer
import structlog

from duckagent.bus import Message, MessageBus
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
    """启动 TUI 交互模式"""
    from duckagent.cli.tui.app import DuckApp
    duck_app = DuckApp()
    duck_app.run()


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
