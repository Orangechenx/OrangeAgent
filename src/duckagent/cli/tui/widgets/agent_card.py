from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


_STATE_INDICATORS = {
    "idle": ("●", "dim"),
    "thinking": ("●", "yellow"),
    "tool_calling": ("●", "blue"),
}


class AgentCard(Widget):
    DEFAULT_CSS = """
    AgentCard {
        height: auto;
        min-height: 5;
        margin: 0 0 1 0;
        padding: 1;
        border: solid $surface-lighten-2;
    }
    AgentCard .agent-name {
        text-style: bold;
    }
    AgentCard .agent-status {
        margin-left: 1;
    }
    AgentCard .agent-task {
        color: $text-muted;
        margin-top: 1;
    }
    AgentCard .agent-conclusion {
        color: $text-disabled;
        margin-top: 0;
    }
    """

    state: reactive[str] = reactive("idle")
    task_summary: reactive[str] = reactive("等待任务")
    last_conclusion: reactive[str] = reactive("")

    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id

    def compose(self) -> ComposeResult:
        yield Static(self.agent_id, classes="agent-name")
        yield Static("", id="status-indicator", classes="agent-status")
        yield Static("", id="task-label", classes="agent-task")
        yield Static("", id="conclusion-label", classes="agent-conclusion")

    def on_mount(self) -> None:
        self._refresh_display()

    def update_status(self, state: str, task_summary: str = "", last_conclusion: str = "") -> None:
        self.state = state
        if task_summary:
            self.task_summary = task_summary
        if last_conclusion:
            self.last_conclusion = last_conclusion

    def watch_state(self) -> None:
        self._refresh_display()

    def watch_task_summary(self) -> None:
        self._refresh_display()

    def watch_last_conclusion(self) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        indicator, color = _STATE_INDICATORS.get(self.state, ("●", "dim"))
        try:
            self.query_one("#status-indicator", Static).update(
                f"[{color}]{indicator}[/] {self.state}"
            )
            self.query_one("#task-label", Static).update(f"处理: {self.task_summary}")
            conclusion_text = self.last_conclusion[:60] + "..." if len(self.last_conclusion) > 60 else self.last_conclusion
            self.query_one("#conclusion-label", Static).update(
                f"结论: {conclusion_text}" if conclusion_text else ""
            )
        except Exception:
            pass
