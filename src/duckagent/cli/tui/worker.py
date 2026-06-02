import asyncio
import json

from textual.app import App
from textual.containers import VerticalScroll
from textual.css.query import NoMatches

from duckagent.bus.models import Message
from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.message import MessageWidget


async def consume_observer_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    """Consume ALL messages from the bus observer and render non-status messages.

    Human messages are rendered immediately in on_input_area_submitted,
    so we skip them here to avoid duplicates.
    All other messages (agent→human, agent↔agent) are rendered here.
    """
    while True:
        msg = await queue.get()
        if msg.type == "status":
            continue
        # Human messages are already mounted immediately on submit
        if msg.from_agent == "human":
            continue
        try:
            container = app.query_one("#messages", VerticalScroll)
            widget = MessageWidget(msg)
            container.mount(widget)
            container.scroll_end(animate=False)
        except (NoMatches, Exception):
            break


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
        try:
            for card in app.query(AgentCard):
                if card.agent_id == msg.from_agent:
                    card.update_status(
                        state=data.get("state", "idle"),
                        task_summary=data.get("task_summary", ""),
                        last_conclusion=data.get("last_conclusion", ""),
                    )
                    break
        except (NoMatches, Exception):
            break
