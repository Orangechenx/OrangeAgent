from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from duckagent.bus.models import Message


class MessageHeader(Static):
    DEFAULT_CSS = """
    MessageHeader {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """


class MessageWidget(Widget):
    DEFAULT_CSS = """
    MessageWidget {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    def __init__(self, msg: Message) -> None:
        super().__init__()
        self._msg = msg

    def compose(self) -> ComposeResult:
        msg = self._msg
        ts = msg.timestamp.strftime("%H:%M") if isinstance(msg.timestamp, datetime) else str(msg.timestamp)[:5]
        from_label = "you" if msg.from_agent == "human" else msg.from_agent
        to_label = "you" if msg.to_agent == "human" else (msg.to_agent or "all")
        yield MessageHeader(f"[{ts}] {from_label} → {to_label}")
        yield Markdown(msg.content)
