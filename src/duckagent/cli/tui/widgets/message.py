from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Markdown, Static

from duckagent.bus.models import Message

_TYPE_ICONS = {
    "request": "📤",
    "conclusion": "📋",
    "question": "❓",
    "decision": "✋",
    "status": "🔄",
}


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
        border-left: vkey $surface;
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
        icon = _TYPE_ICONS.get(msg.type, "💬")

        # Build mentions display
        mentions_display = ""
        if msg.mentions:
            mention_labels = [f"@{m}" for m in msg.mentions]
            mentions_display = " [" + ", ".join(mention_labels) + "]"

        # Add CSS classes for styling
        if msg.from_agent == "human":
            self.add_class("msg-human")
        elif msg.to_agent == "human":
            self.add_class("msg-to-human")
        else:
            self.add_class("msg-agent")

        self.add_class(f"msg-type-{msg.type}")

        yield MessageHeader(f"{icon} [{ts}] {from_label} → {to_label}{mentions_display}")
        yield Markdown(msg.content)
