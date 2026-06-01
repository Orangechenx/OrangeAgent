from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class InputArea(Widget):
    """Auto-expanding text input area. Enter submits, Shift+Enter inserts newline."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def compose(self) -> ComposeResult:
        yield TextArea(id="input-text")

    def on_mount(self) -> None:
        self.query_one("#input-text", TextArea).focus()

    @property
    def text(self) -> str:
        return self.query_one("#input-text", TextArea).text

    @text.setter
    def text(self, value: str) -> None:
        self.query_one("#input-text", TextArea).text = value

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Detect newline (Enter) in the TextArea and trigger submit."""
        if event.text_area.id != "input-text":
            return
        text = event.text_area.text
        if "\n" in text:
            content = text.strip("\n")
            if content.strip():
                self.post_message(self.Submitted(content.strip()))
            event.text_area.text = ""
