from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class InputArea(Widget):
    BINDINGS = [
        Binding("enter", "submit", "发送", show=False),
    ]

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    DEFAULT_CSS = """
    InputArea {
        height: auto;
        max-height: 12;
        padding: 0 1;
    }
    InputArea TextArea {
        height: auto;
        max-height: 10;
        min-height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield TextArea(id="input-text")

    @property
    def text(self) -> str:
        return self.query_one("#input-text", TextArea).text

    @text.setter
    def text(self, value: str) -> None:
        self.query_one("#input-text", TextArea).text = value

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Detect Enter key (newline) in the TextArea and trigger submit."""
        if event.text_area.id == "input-text" and "\n" in event.text_area.text:
            content = event.text_area.text.strip("\n")
            if content.strip():
                self.post_message(self.Submitted(content))
            event.text_area.text = ""

    def action_submit(self) -> None:
        text = self.text.strip()
        if not text:
            return
        self.post_message(self.Submitted(text))
        self.text = ""
