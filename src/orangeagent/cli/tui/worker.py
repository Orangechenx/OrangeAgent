import asyncio
import json

from textual.app import App
from textual.containers import VerticalScroll
from textual.css.query import NoMatches

from orangeagent.bus.models import Message
from orangeagent.cli.tui.widgets.agent_card import AgentCard
from orangeagent.cli.tui.widgets.message import MessageWidget

import structlog
logger = structlog.get_logger()


async def consume_observer_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    """Consume ALL messages from the bus observer and render non-status messages.

    Human messages are rendered immediately in on_input_area_submitted,
    so we skip them here to avoid duplicates.
    All other messages (agent→human, agent↔agent) are rendered here.
    异常时会记录日志并继续，不会静默退出。
    """
    while True:
        try:
            msg = await queue.get()
        except Exception:
            logger.exception("observer_queue_get_failed")
            await asyncio.sleep(0.5)
            continue
        if msg.type == "status":
            continue
        if msg.from_agent == "human":
            continue
        try:
            container = app.query_one("#messages", VerticalScroll)
            widget = MessageWidget(msg)
            container.mount(widget)
            container.scroll_end(animate=False)
        except NoMatches:
            # App 尚未 mount 完毕或已 unmount
            await asyncio.sleep(0.1)
            continue
        except Exception as exc:
            logger.exception("observer_render_failed", error=str(exc))
            await asyncio.sleep(0.1)
            continue


async def consume_status_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    """Consume status messages from agents and update AgentCard widgets.
    异常时会记录日志并继续，不会静默退出。
    """
    while True:
        try:
            msg = await queue.get()
        except Exception:
            logger.exception("status_queue_get_failed")
            await asyncio.sleep(0.5)
            continue
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
        except NoMatches:
            await asyncio.sleep(0.1)
            continue
        except Exception as exc:
            logger.exception("status_update_failed", error=str(exc))
            continue
