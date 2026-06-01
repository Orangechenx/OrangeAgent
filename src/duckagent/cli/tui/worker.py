import asyncio
import json

from textual.app import App
from textual.containers import VerticalScroll

from duckagent.bus.models import Message
from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.message import MessageWidget


async def consume_human_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    """Consume messages addressed to human and render them in the #messages panel."""
    while True:
        msg = await queue.get()
        if msg.type == "status":
            continue
        container = app.query_one("#messages", VerticalScroll)
        widget = MessageWidget(msg)
        container.mount(widget)
        container.scroll_end(animate=False)


async def consume_status_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    """Consume status messages from agents and update AgentCard widgets."""
    while True:
        msg = await queue.get()
        if msg.type != "status":
            continue
        try:
            data = json.loads(msg.content)
        except Exception:
            continue
        for card in app.query(AgentCard):
            if card.agent_id == msg.from_agent:
                card.update_status(
                    state=data.get("state", "idle"),
                    task_summary=data.get("task_summary", ""),
                    last_conclusion=data.get("last_conclusion", ""),
                )
                break
