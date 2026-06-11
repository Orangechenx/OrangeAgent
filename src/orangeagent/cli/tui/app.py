import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Label

from orangeagent.agents.main_agent import MainAgent
from orangeagent.agents.trace_agent import TraceAgent
from orangeagent.agents.ida_jadx_agent import IdaJadxAgent
from orangeagent.agents.frida_agent import FridaAgent
from orangeagent.agents.network_agent import NetworkAgent
from orangeagent.agents.apktool_agent import ApktoolAgent
from orangeagent.agents.js_reverse_agent import JsReverseAgent
from orangeagent.agents.ida_agent import IdaAgent
from orangeagent.agents.unidbg_agent import UnidbgAgent
from orangeagent.bus.interface import MessageBus
from orangeagent.bus.store import LocalMessageBus
from orangeagent.bus.models import Message
from orangeagent.config import settings
from orangeagent.cli.tui.widgets.agent_card import AgentCard
from orangeagent.cli.tui.widgets.input_area import InputArea
from orangeagent.cli.tui.widgets.message import MessageWidget
from orangeagent.cli.tui.worker import consume_status_queue, consume_observer_queue

import structlog
logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 所有 agent 类型定义： (agent_id, cls, extra_kwargs)
_ALL_AGENTS = [
    ("main_agent", MainAgent, {}),
    ("trace_agent", TraceAgent, {}),
    ("ida_jadx_agent", IdaJadxAgent, {}),
    ("frida_agent", FridaAgent, {}),
    ("network_agent", NetworkAgent, {}),
    ("apktool_agent", ApktoolAgent, {}),
    ("js_reverse_agent", JsReverseAgent, {}),
    ("ida_agent", IdaAgent, {}),
    ("unidbg_agent", UnidbgAgent, {}),
]


class DuckApp(App):
    CSS_PATH = str(Path(__file__).parent / "app.tcss")
    TITLE = "OrangeAgent"
    BINDINGS = [
        Binding("ctrl+l", "clear_messages", "清屏"),
        Binding("ctrl+d", "quit", "退出", priority=True),
        Binding("ctrl+h", "show_help", "帮助", priority=False),
    ]

    def __init__(self, bus: MessageBus | None = None, http_mode: bool = False) -> None:
        super().__init__()
        self._external_bus = bus
        self._http_mode = http_mode
        self._bus: MessageBus | None = None
        self._agents: dict[str, object] = {}
        self._status_task: asyncio.Task[None] | None = None
        self._observer_task: asyncio.Task[None] | None = None
        self._observer_queue: asyncio.Queue[Message] | None = None

    async def _create_agent(self, agent_id: str, agent_cls: type, prompts_dir: Path, agent_md_path: Path | None) -> object:
        extra = {}
        if agent_id == "main_agent" and agent_md_path:
            main_kwargs = {"agent_md_path": agent_md_path}
        else:
            main_kwargs = {}

        if agent_id == "trace_agent":
            extra["trace_files"] = settings.trace_files or None
        if agent_id == "ida_jadx_agent":
            extra["jadx_host"] = settings.jadx_host
            extra["jadx_port"] = settings.jadx_port

        return agent_cls(
            bus=self._bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
            **extra, **main_kwargs,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("加载中...", id="loading-label")
        yield VerticalScroll(id="messages")
        yield VerticalScroll(id="agents")
        yield InputArea()
        yield Footer()

    async def on_mount(self) -> None:
        agents_panel = self.query_one("#agents", VerticalScroll)
        for agent_id, _, _ in _ALL_AGENTS:
            await agents_panel.mount(AgentCard(agent_id=agent_id))

        if self._http_mode and self._external_bus:
            self._bus = self._external_bus
            await self._bus.initialize()
        else:
            self._bus = LocalMessageBus(db_path=settings.db_path)
            await self._bus.initialize()

            prompts_dir = Path(settings.prompts_dir)
            agent_md_path = _PROJECT_ROOT / "AGENT.md"

            for agent_id, agent_cls, _ in _ALL_AGENTS:
                extra = {}
                if agent_id == "trace_agent":
                    extra["trace_files"] = settings.trace_files or None
                if agent_id == "ida_jadx_agent":
                    extra["jadx_host"] = settings.jadx_host
                    extra["jadx_port"] = settings.jadx_port

                agent = agent_cls(
                    bus=self._bus,
                    model=settings.litellm_model,
                    prompts_dir=prompts_dir,
                    agent_md_path=agent_md_path if agent_id == "main_agent" else None,
                    verify_enabled=settings.verify_enabled,
                    verify_max_retries=settings.verify_max_retries,
                    **extra,
                )
                self._agents[agent_id] = agent
                await agent.start()

        # Observer sees ALL messages
        self._observer_queue = self._bus.add_observer()
        status_queue = self._bus.subscribe("_tui")

        self._observer_task = asyncio.create_task(consume_observer_queue(self, self._observer_queue))
        self._status_task = asyncio.create_task(consume_status_queue(self, status_queue))

        asyncio.create_task(self._load_history())

    async def _load_history(self) -> None:
        assert self._bus is not None
        try:
            history = await self._bus.get_history(limit=20)
        except Exception as exc:
            logger.warning("history_load_failed", error=str(exc))
            self._hide_loading()
            return
        self._hide_loading()
        if not history:
            return
        container = self.query_one("#messages", VerticalScroll)
        for msg in history:
            if msg.type == "status":
                continue
            try:
                container.mount(MessageWidget(msg))
            except Exception:
                continue
        container.scroll_end(animate=False)

    def _hide_loading(self) -> None:
        try:
            self.query_one("#loading-label").remove()
        except Exception:
            pass

    async def on_unmount(self) -> None:
        if self._status_task:
            self._status_task.cancel()
        if self._observer_task:
            self._observer_task.cancel()
        if self._observer_queue and self._bus:
            self._bus.remove_observer(self._observer_queue)
        for agent in self._agents.values():
            try:
                await agent.stop()
            except Exception:
                pass
        if self._bus:
            await self._bus.close()

    def on_input_area_submitted(self, event: InputArea.Submitted) -> None:
        from orangeagent.agents.base import _AT_MENTION_RE
        mentions = list(dict.fromkeys(_AT_MENTION_RE.findall(event.value)))
        msg = Message(
            from_agent="human", to_agent="main_agent", mentions=mentions,
            type="request", content=event.value, evidence=[], confidence="high",
        )
        container = self.query_one("#messages", VerticalScroll)
        container.mount(MessageWidget(msg))
        container.scroll_end(animate=False)

        async def _publish_safe(msg: Message) -> None:
            try:
                assert self._bus is not None
                await self._bus.publish(msg)
            except Exception as e:
                logger.error("publish_failed", error=str(e))

        asyncio.create_task(_publish_safe(msg))

    def action_clear_messages(self) -> None:
        self.query_one("#messages", VerticalScroll).remove_children()

    def action_show_help(self) -> None:
        from textual.screen import Screen
        from textual.widgets import Static

        help_screen = Screen()
        help_lines = [
            "[bold]OrangeAgent 快捷键帮助[/bold]\n",
            "[bold]Ctrl+D[/bold]  退出应用",
            "[bold]Ctrl+L[/bold]  清屏",
            "[bold]Ctrl+H[/bold]  显示本帮助\n",
            "输入时:",
            "  [bold]Enter[/bold]  发送消息",
            "  [bold]Shift+Enter[/bold]  换行\n",
            "可用的 Agent:",
        ]
        for agent_id, _, _ in _ALL_AGENTS:
            help_lines.append(f"  @{agent_id}")
        help_lines.append("")
        help_lines.append("例: @trace_agent 分析这个签名")

        help_screen.compose = lambda: ComposeResult(Static("\n".join(help_lines)))
        help_screen.BINDINGS = [
            Binding("escape", "dismiss", "关闭", priority=True),
            Binding("q", "dismiss", "关闭", priority=True),
        ]
        self.push_screen(help_screen)
