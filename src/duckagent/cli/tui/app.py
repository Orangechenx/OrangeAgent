import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header

from duckagent.agents.main_agent import MainAgent
from duckagent.agents.trace_agent import TraceAgent
from duckagent.bus.store import MessageBus
from duckagent.bus.models import Message
from duckagent.config import settings
from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.input_area import InputArea
from duckagent.cli.tui.widgets.message import MessageWidget
from duckagent.cli.tui.worker import consume_human_queue, consume_status_queue


class DuckApp(App):
    CSS_PATH = str(Path(__file__).parent / "app.tcss")
    TITLE = "DuckAgent"
    BINDINGS = [
        ("ctrl+l", "clear_messages", "清屏"),
        ("ctrl+q", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._bus: MessageBus | None = None
        self._main_agent: MainAgent | None = None
        self._trace_agent: TraceAgent | None = None
        self._human_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="messages")
        yield VerticalScroll(id="agents")
        yield InputArea()
        yield Footer()

    async def on_mount(self) -> None:
        agents_panel = self.query_one("#agents", VerticalScroll)
        await agents_panel.mount(AgentCard(agent_id="main_agent"))
        await agents_panel.mount(AgentCard(agent_id="trace_agent"))

        self._bus = MessageBus(db_path=settings.db_path)
        await self._bus.initialize()

        prompts_dir = Path(settings.prompts_dir)
        agent_md_path = Path("AGENT.md")

        self._main_agent = MainAgent(
            bus=self._bus,
            model=settings.litellm_model,
            agent_md_path=agent_md_path,
            prompts_dir=prompts_dir,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )
        self._trace_agent = TraceAgent(
            bus=self._bus,
            model=settings.litellm_model,
            prompts_dir=prompts_dir,
            trace_files=settings.trace_files or None,
            verify_enabled=settings.verify_enabled,
            verify_max_retries=settings.verify_max_retries,
        )

        await self._main_agent.start()
        await self._trace_agent.start()

        human_queue = self._bus.subscribe("human")
        status_queue = self._bus.subscribe("_tui")

        self._human_task = asyncio.create_task(consume_human_queue(self, human_queue))
        self._status_task = asyncio.create_task(consume_status_queue(self, status_queue))

    async def on_unmount(self) -> None:
        if self._human_task:
            self._human_task.cancel()
        if self._status_task:
            self._status_task.cancel()
        if self._main_agent:
            await self._main_agent.stop()
        if self._trace_agent:
            await self._trace_agent.stop()
        if self._bus:
            await self._bus.close()

    def on_input_area_submitted(self, event: InputArea.Submitted) -> None:
        msg = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content=event.value,
            evidence=[],
            confidence="high",
        )
        container = self.query_one("#messages", VerticalScroll)
        container.mount(MessageWidget(msg))
        container.scroll_end(animate=False)
        asyncio.create_task(self._bus.publish(msg))

    def action_clear_messages(self) -> None:
        container = self.query_one("#messages", VerticalScroll)
        container.remove_children()
