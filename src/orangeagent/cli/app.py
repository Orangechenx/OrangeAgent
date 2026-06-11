import asyncio
import functools
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import typer
import structlog
from rich.console import Console
from rich.table import Table

from orangeagent.bus import Message, LocalMessageBus
from orangeagent.config import settings

logger = structlog.get_logger()

console = Console()
app = typer.Typer(
    name="orange",
    help="OrangeAgent - Android 逆向 Multi-Agent 系统",
    no_args_is_help=True,
)


# ── 版本 ────────────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        from orangeagent import __version__
        typer.echo(f"OrangeAgent v{__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(False, "--version", "-V", help="显示版本信息", callback=_version_callback),
) -> None:
    pass


# ── Bus 连接管理 ────────────────────────────────────────────────


@asynccontextmanager
async def get_bus(transport: str = "local", server_url: str | None = None):
    if transport == "http":
        from orangeagent.bus.http_client import HttpMessageBus

        bus = HttpMessageBus(server_url=server_url or settings.bus_server_url, agent_id=None)
    else:
        bus = LocalMessageBus(db_path=settings.db_path)
    await bus.initialize()
    try:
        yield bus
    finally:
        await bus.close()


def bus_command(async_fn):
    """减少样板代码：自动处理 bus 连接和 asyncio.run。"""

    @functools.wraps(async_fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        transport = kwargs.pop("transport", "local")
        server_url = kwargs.pop("server_url", None)

        async def _run():
            async with get_bus(transport, server_url) as bus:
                return await async_fn(bus, *args, **kwargs)

        asyncio.run(_run())

    return wrapper


def format_message(msg: Message) -> str:
    ts = msg.timestamp.strftime("%H:%M") if isinstance(msg.timestamp, datetime) else str(msg.timestamp)[:5]
    target = msg.to_agent or "all"
    if target == "human":
        target = "you"
    return f"[{ts}] {msg.from_agent} → {target}: {msg.content}"


def _add_transport_opts(cmd: typer.Typer) -> None:
    """Transport options are handled by bus_command decorator."""
    pass


# ── Core commands ──────────────────────────────────────────────


@app.command()
def run(
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """启动 TUI 交互模式"""
    if transport == "http":
        url = server_url or settings.bus_server_url
        from orangeagent.bus.http_client import HttpMessageBus
        from orangeagent.cli.tui.app import DuckApp
        bus = HttpMessageBus(server_url=url, agent_id=None)
        duck_app = DuckApp(bus=bus, http_mode=True)
        duck_app.run()
    else:
        from orangeagent.cli.tui.app import DuckApp
        duck_app = DuckApp()
        duck_app.run()


@app.command()
def send(
    message: str,
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """发送消息给主 Agent（非交互模式）"""
    asyncio.run(_send_message(message, transport, server_url))


@app.command()
def log(
    from_agent: str = typer.Option(None, "--from", help="按发送者过滤"),
    limit: int = typer.Option(50, "--limit", help="消息数量限制"),
    msg_type: str = typer.Option(None, "--type", help="按消息类型过滤"),
):
    """查看消息历史"""
    asyncio.run(_show_log(from_agent, limit, msg_type))


@app.command("list")
def list_tasks(
    session_id: str = typer.Option(None, "--session-id", help="按 session 过滤"),
    limit: int = typer.Option(50, "--limit", help="任务数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看任务运行状态"""
    asyncio.run(_show_tasks(session_id, limit, transport, server_url))


@app.command()
def tasks(
    session_id: str = typer.Option(None, "--session-id", help="按 session 过滤"),
    limit: int = typer.Option(50, "--limit", help="任务数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看任务运行状态（等价于 list）"""
    asyncio.run(_show_tasks(session_id, limit, transport, server_url))


@app.command()
def runs(
    session_id: str = typer.Option(None, "--session-id", help="按 session 过滤"),
    run_id: str = typer.Option(None, "--run-id", help="按 run 过滤"),
    limit: int = typer.Option(50, "--limit", help="run 数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看 run 运行状态与恢复点"""
    asyncio.run(_show_runs(session_id, run_id, limit, transport, server_url))


@app.command()
def memory(
    session_id: str = typer.Option(None, "--session-id", help="按 session 过滤"),
    task_id: str = typer.Option(None, "--task-id", help="按 task 过滤"),
    limit: int = typer.Option(50, "--limit", help="记忆数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看 agent 记忆与权重"""
    asyncio.run(_show_memory(session_id, task_id, limit, transport, server_url))


@app.command()
def evidence(
    task_id: str = typer.Option(..., "--task-id", help="任务 ID"),
    limit: int = typer.Option(50, "--limit", help="证据数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看任务证据库"""
    asyncio.run(_show_evidence(task_id, limit, transport, server_url))


@app.command()
def tools(
    task_id: str = typer.Option(None, "--task-id", help="按 task 过滤"),
    limit: int = typer.Option(50, "--limit", help="工具调用数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看工具调用审计"""
    asyncio.run(_show_tools(task_id, limit, transport, server_url))


@app.command()
def handoffs(
    task_id: str = typer.Option(None, "--task-id", help="按 task 过滤"),
    run_id: str = typer.Option(None, "--run-id", help="按 run 过滤"),
    limit: int = typer.Option(50, "--limit", help="handoff 数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看结构化 handoff 协作记录"""
    asyncio.run(_show_handoffs(task_id, run_id, limit, transport, server_url))


@app.command()
def steps(
    task_id: str = typer.Option(None, "--task-id", help="按 task 过滤"),
    run_id: str = typer.Option(None, "--run-id", help="按 run 过滤"),
    limit: int = typer.Option(100, "--limit", help="运行步骤数量限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """查看 run step 执行审计"""
    asyncio.run(_show_steps(task_id, run_id, limit, transport, server_url))


@app.command()
def context(
    session_id: str = typer.Option(..., "--session-id", help="Session ID"),
    task_id: str = typer.Option(None, "--task-id", help="Task ID"),
    query: str = typer.Option("", "--query", help="当前问题，用于记忆打分"),
    limit: int = typer.Option(8, "--limit", help="返回条数限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """预览注入给 agent 的记忆上下文"""
    asyncio.run(_show_context(session_id, task_id, query, limit, transport, server_url))


@app.command()
def system_context(
    limit: int = typer.Option(15, "--limit", help="返回条数限制"),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """预览合成进 system prompt 的持久记忆"""
    asyncio.run(_show_system_context(limit, transport, server_url))


@app.command()
def cleanup(
    max_memories_per_task: int = typer.Option(
        100,
        "--max-memories-per-task",
        help="每个任务保留的 tentative 记忆数量",
    ),
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """清理过量低价值 runtime 记录"""
    asyncio.run(_cleanup_runtime(max_memories_per_task, transport, server_url))


@app.command("eval")
def eval_command(
    transport: str = typer.Option("local", "--transport", help="Bus transport: local | http"),
    server_url: str = typer.Option(None, "--server-url", help="Bus server URL (http mode)"),
):
    """评估 runtime 完整度"""
    asyncio.run(_run_eval(transport, server_url))


# ── HTTP / multi-process commands ──────────────────────────────


@app.command()
def server(
    port: int = typer.Option(8720, "--port", help="Bus server port"),
):
    """启动 HTTP 消息总线服务"""
    import uvicorn
    from orangeagent.server.app import app as bus_app
    uvicorn.run(bus_app, host="127.0.0.1", port=port, log_level="info")


@app.command()
def launch(
    port: int = typer.Option(8720, "--port", help="Bus server port"),
):
    """启动全部进程（server + agents + TUI）"""
    from orangeagent.launcher import Launcher
    launcher = Launcher(server_port=port)
    launcher.start()


@app.command()
def agent(
    agent_type: str = typer.Argument(..., help="Agent type: main_agent | trace_agent | ida_jadx_agent"),
    server_url: str = typer.Option(..., "--server-url", help="Bus server URL"),
):
    """启动单个 Agent 进程"""
    from orangeagent.processes.agent_process import run_agent
    asyncio.run(run_agent(agent_type, server_url))


# ── Internals ──────────────────────────────────────────────────


async def _show_log(from_agent: str | None, limit: int, msg_type: str | None):
    async with get_bus() as bus:
        history = await bus.get_history(limit=limit, from_agent=from_agent, msg_type=msg_type)
        if not history:
            typer.echo("没有消息")
            return
        for msg in history:
            typer.echo(format_message(msg))


async def _send_message(content: str, transport: str, server_url: str | None):
    async with get_bus(transport, server_url) as bus:
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
        typer.echo(f"session_id={msg.session_id} task_id={msg.task_id} run_id={msg.run_id}")
        if transport == "local":
            typer.echo("提示: local 模式仅写入本地总线；需要 orange run 才会有 agent 消费。")


async def _show_tasks(session_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        task_list = await bus.get_tasks(session_id=session_id, limit=limit)
        if not task_list:
            typer.echo("没有任务")
            return
        table = Table(title=f"任务列表 (共 {len(task_list)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("状态/阶段")
        table.add_column("Session")
        table.add_column("负责人")
        table.add_column("标题")
        for task in task_list:
            table.add_row(
                task.id[:8],
                f"[{task.status}/{task.phase}]",
                task.session_id[:8],
                task.owner_agent,
                task.title[:80],
            )
        console.print(table)


async def _show_runs(session_id: str | None, run_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        run_list = await bus.get_runs(session_id=session_id, run_id=run_id, limit=limit)
        if not run_list:
            typer.echo("没有 run")
            return
        table = Table(title=f"Run 列表 (共 {len(run_list)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("状态/阶段")
        table.add_column("Task")
        table.add_column("检查点")
        table.add_column("摘要")
        for run in run_list:
            checkpoint = run.checkpoint_step_id[:8] if run.checkpoint_step_id else "-"
            table.add_row(
                run.id[:8],
                f"[{run.status}/{run.phase}]",
                (run.task_id or "")[:8],
                checkpoint,
                run.summary[:80],
            )
        console.print(table)


async def _show_memory(session_id: str | None, task_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        memories = await bus.get_memories(session_id=session_id, task_id=task_id, limit=limit)
        if not memories:
            typer.echo("没有记忆")
            return
        table = Table(title=f"记忆列表 (共 {len(memories)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("权重")
        table.add_column("状态")
        table.add_column("来源")
        table.add_column("置信度")
        table.add_column("内容")
        for memory in memories:
            table.add_row(
                memory.id[:8],
                f"{memory.weight:.2f}",
                memory.status,
                memory.source,
                memory.confidence,
                memory.content[:80],
            )
        console.print(table)


async def _show_evidence(task_id: str, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        items = await bus.get_evidence(task_id=task_id, limit=limit)
        if not items:
            typer.echo("没有证据")
            return
        table = Table(title=f"证据列表 (共 {len(items)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("类型/来源")
        table.add_column("引用")
        table.add_column("内容")
        for item in items:
            table.add_row(
                item.id[:8],
                f"[{item.type}/{item.source}]",
                item.ref[:40],
                item.content[:80],
            )
        console.print(table)


async def _show_tools(task_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        records = await bus.get_tool_calls(task_id=task_id, limit=limit)
        if not records:
            typer.echo("没有工具调用")
            return
        table = Table(title=f"工具调用 (共 {len(records)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("状态")
        table.add_column("Agent")
        table.add_column("工具")
        table.add_column("耗时")
        table.add_column("结果预览")
        for record in records:
            table.add_row(
                record.id[:8],
                record.status,
                record.agent_id,
                record.tool_name,
                f"{record.duration_ms}ms",
                record.result_preview[:80],
            )
        console.print(table)


async def _show_handoffs(task_id: str | None, run_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        records = await bus.get_handoffs(task_id=task_id, run_id=run_id, limit=limit)
        if not records:
            typer.echo("没有 handoff")
            return
        table = Table(title=f"Handoff 记录 (共 {len(records)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("状态")
        table.add_column("来源")
        table.add_column("目标")
        table.add_column("原因")
        for record in records:
            table.add_row(
                record.id[:8],
                record.status,
                record.from_agent,
                record.to_agent,
                record.reason[:80],
            )
        console.print(table)


async def _show_steps(task_id: str | None, run_id: str | None, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        records = await bus.get_run_steps(task_id=task_id, run_id=run_id, limit=limit)
        if not records:
            typer.echo("没有运行步骤")
            return
        table = Table(title=f"运行步骤 (共 {len(records)} 条)")
        table.add_column("ID", style="dim")
        table.add_column("状态/类型")
        table.add_column("Agent")
        table.add_column("耗时")
        table.add_column("标题")
        for record in records:
            table.add_row(
                record.id[:8],
                f"[{record.status}/{record.step_type}]",
                record.agent_id,
                f"{record.duration_ms}ms",
                record.title[:80],
            )
        console.print(table)


async def _show_context(session_id: str, task_id: str | None, query: str, limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        context_text = await bus.build_context(
            session_id=session_id,
            task_id=task_id,
            query=query,
            limit=limit,
        )
        typer.echo(context_text or "没有可注入上下文")


async def _show_system_context(limit: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        context_text = await bus.build_system_context(limit=limit)
        typer.echo(context_text or "没有持久记忆")


async def _cleanup_runtime(max_memories_per_task: int, transport: str, server_url: str | None) -> None:
    async with get_bus(transport, server_url) as bus:
        result = await bus.cleanup_runtime(max_memories_per_task=max_memories_per_task)
        typer.echo(f"已归档记忆: {result.get('archived_memories', 0)}")


async def _run_eval(transport: str, server_url: str | None) -> None:
    from orangeagent.eval import evaluate_runtime

    async with get_bus(transport, server_url) as bus:
        result = await evaluate_runtime(bus)
        typer.echo(f"runtime 评分: {result.score}/100")
        typer.echo(result.summary)
        for warning in result.warnings:
            typer.echo(f"警告: {warning}")
