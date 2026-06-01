# Textual TUI 面板式界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Textual 替换 print-based CLI 的 `duck run` 命令，实现面板式 TUI（左侧 markdown 消息历史 + 右侧 agent 状态 + 底部自适应输入）。

**Architecture:** Textual App 全接管 asyncio 事件循环，agent 生命周期跟随 App mount/unmount。MessageBus 新增 ephemeral status 消息类型驱动 agent 状态面板更新。

**Tech Stack:** Python 3.12+, Textual >=3.0, typer (保留非 TUI 子命令), pydantic v2

---

### Task 1: 添加 textual 依赖 + 扩展 Message 模型

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/duckagent/bus/models.py`
- Modify: `tests/test_bus.py`

- [ ] **Step 1: 添加 textual 依赖**

在 `pyproject.toml` 的 dependencies 中添加：

```toml
"textual>=3.0",
```

- [ ] **Step 2: 扩展 Message.type 支持 status**

`src/duckagent/bus/models.py` 中将 type 字段改为：

```python
type: Literal["conclusion", "request", "question", "decision", "status"]
```

- [ ] **Step 3: 写测试验证 status 类型消息可创建**

在 `tests/test_bus.py` 中添加：

```python
def test_message_status_type():
    msg = Message(
        from_agent="main_agent",
        to_agent=None,
        type="status",
        content='{"state": "thinking", "task_summary": "分析请求"}',
        evidence=[],
        confidence="high",
    )
    assert msg.type == "status"
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_bus.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/duckagent/bus/models.py tests/test_bus.py
git commit -m "feat: add textual dep and status message type"
```

---

### Task 2: MessageBus 支持 ephemeral 消息

**Files:**
- Modify: `src/duckagent/bus/store.py`
- Modify: `tests/test_bus.py`

- [ ] **Step 1: 写测试验证 status 消息不持久化**

在 `tests/test_bus.py` 中添加：

```python
@pytest.mark.asyncio
async def test_status_message_not_persisted(tmp_path):
    bus = MessageBus(db_path=tmp_path / "test.db")
    await bus.initialize()

    msg = Message(
        from_agent="main_agent",
        to_agent=None,
        type="status",
        content='{"state": "thinking"}',
        evidence=[],
        confidence="high",
    )
    await bus.publish(msg)

    history = await bus.get_history(limit=100)
    assert len(history) == 0

    await bus.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_bus.py::test_status_message_not_persisted -v`
Expected: FAIL (status message currently gets persisted)

- [ ] **Step 3: 修改 publish 跳过 status 持久化**

`src/duckagent/bus/store.py` 中修改 `publish` 方法：

```python
async def publish(self, msg: Message) -> None:
    if msg.type != "status":
        await self._persist(msg)
    self._dispatch(msg)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_bus.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/bus/store.py tests/test_bus.py
git commit -m "feat: skip persistence for ephemeral status messages"
```

---

### Task 3: BaseAgent 状态广播

**Files:**
- Modify: `src/duckagent/agents/base.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: 写测试验证 think() 广播状态**

在 `tests/test_agents.py` 中添加：

```python
@pytest.mark.asyncio
async def test_agent_broadcasts_thinking_status(tmp_path):
    bus = MessageBus(db_path=tmp_path / "test.db")
    await bus.initialize()

    status_queue = bus.subscribe("_tui")

    agent = BaseAgent(
        agent_id="test_agent",
        system_prompt="test",
        bus=bus,
        model="fake/model",
        verify_enabled=False,
    )

    with patch("litellm.acompletion") as mock_llm:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hello"
        mock_response.choices[0].message.tool_calls = None
        mock_llm.return_value = mock_response

        await agent.think("test input")

    messages = []
    while not status_queue.empty():
        messages.append(await status_queue.get())

    status_msgs = [m for m in messages if m.type == "status"]
    assert len(status_msgs) >= 2
    assert '"state": "thinking"' in status_msgs[0].content
    assert '"state": "idle"' in status_msgs[-1].content

    await bus.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_agents.py::test_agent_broadcasts_thinking_status -v`
Expected: FAIL

- [ ] **Step 3: 在 think() 中添加状态广播**

在 `src/duckagent/agents/base.py` 的 `think()` 方法中，调用 LLM 前后广播状态：

```python
async def think(self, input_text: str, *, tools: list[dict] | None = None,
                tool_executor: Any = None, max_iterations: int = 50) -> str:
    self.context.append({"role": "user", "content": input_text})
    await self._broadcast_status("thinking", task_summary=input_text[:80])

    for _ in range(max_iterations):
        kwargs: dict[str, Any] = {"model": self.model, "messages": self.context}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._call_llm_with_retry(**kwargs)
        message = response.choices[0].message

        assistant_entry: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            assistant_entry["tool_calls"] = [
                tc.model_dump() if hasattr(tc, "model_dump") else tc
                for tc in tool_calls
            ]
        self.context.append(assistant_entry)

        if not tool_calls:
            await self._broadcast_status("idle")
            return message.content or ""

        if not tool_executor:
            await self._broadcast_status("idle")
            return message.content or ""

        await self._broadcast_status("tool_calling")
        for tc in tool_calls:
            name = tc.function.name
            arguments = json.loads(tc.function.arguments)
            result = tool_executor.execute(name, arguments)
            self.context.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": result,
            })

    await self._broadcast_status("idle")
    return "Reached max iterations without final answer."
```

并添加辅助方法：

```python
async def _broadcast_status(self, state: str, task_summary: str = "") -> None:
    import json as _json
    content = _json.dumps({"state": state, "task_summary": task_summary}, ensure_ascii=False)
    msg = Message(
        from_agent=self.agent_id,
        to_agent=None,
        type="status",
        content=content,
        evidence=[],
        confidence="high",
    )
    await self.bus.publish(msg)
```

- [ ] **Step 4: 运行全部 agent 测试**

Run: `uv run pytest tests/test_agents.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/agents/base.py tests/test_agents.py
git commit -m "feat: broadcast agent status via bus"
```

---

### Task 4: InputArea widget（自适应输入框）

**Files:**
- Create: `src/duckagent/cli/tui/__init__.py`
- Create: `src/duckagent/cli/tui/widgets/__init__.py`
- Create: `src/duckagent/cli/tui/widgets/input_area.py`
- Create: `tests/test_tui_widgets.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p src/duckagent/cli/tui/widgets
touch src/duckagent/cli/tui/__init__.py
touch src/duckagent/cli/tui/widgets/__init__.py
```

- [ ] **Step 2: 写 InputArea 测试**

`tests/test_tui_widgets.py`:

```python
import pytest
from textual.app import App, ComposeResult
from textual.widgets import TextArea

from duckagent.cli.tui.widgets.input_area import InputArea


class InputTestApp(App):
    def compose(self) -> ComposeResult:
        yield InputArea()


@pytest.mark.asyncio
async def test_input_area_mounts():
    app = InputTestApp()
    async with app.run_test() as pilot:
        widget = app.query_one(InputArea)
        assert widget is not None


@pytest.mark.asyncio
async def test_input_area_submit():
    app = InputTestApp()
    submitted = []

    def on_submit(message):
        submitted.append(message.value)

    async with app.run_test() as pilot:
        widget = app.query_one(InputArea)
        app.on_input_area_submitted = on_submit
        widget.text = "hello world"
        await pilot.press("enter")
        assert "hello world" in submitted
        assert widget.text == ""
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_tui_widgets.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: 实现 InputArea**

`src/duckagent/cli/tui/widgets/input_area.py`:

```python
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import TextArea
from textual.widget import Widget


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
        dock: bottom;
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

    def action_submit(self) -> None:
        text = self.text.strip()
        if not text:
            return
        self.post_message(self.Submitted(text))
        self.text = ""

    def on_key(self, event) -> None:
        if event.key == "enter" and not event.shift:
            event.prevent_default()
            self.action_submit()
```

- [ ] **Step 5: 运行测试**

Run: `uv run pytest tests/test_tui_widgets.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/duckagent/cli/tui/ tests/test_tui_widgets.py
git commit -m "feat: add InputArea widget with auto-expand"
```

---

### Task 5: MessageWidget（消息渲染组件）

**Files:**
- Create: `src/duckagent/cli/tui/widgets/message.py`
- Modify: `tests/test_tui_widgets.py`

- [ ] **Step 1: 写测试**

在 `tests/test_tui_widgets.py` 中添加：

```python
from datetime import datetime, timezone
from duckagent.bus.models import Message as BusMessage
from duckagent.cli.tui.widgets.message import MessageWidget


class MessageTestApp(App):
    def compose(self) -> ComposeResult:
        msg = BusMessage(
            from_agent="main_agent",
            to_agent="human",
            type="conclusion",
            content="## 分析结果\n\n- AES-128\n- Key at `0x1A40`\n\n```c\nvoid encrypt() {}\n```",
            evidence=["trace line 100"],
            confidence="high",
        )
        yield MessageWidget(msg)


@pytest.mark.asyncio
async def test_message_widget_renders_markdown():
    app = MessageTestApp()
    async with app.run_test() as pilot:
        widget = app.query_one(MessageWidget)
        assert widget is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_tui_widgets.py::test_message_widget_renders_markdown -v`
Expected: FAIL

- [ ] **Step 3: 实现 MessageWidget**

`src/duckagent/cli/tui/widgets/message.py`:

```python
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Markdown, Static

from duckagent.bus.models import Message


_AGENT_COLORS = {
    "human": "bold cyan",
    "main_agent": "bold green",
    "trace_agent": "bold blue",
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
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_tui_widgets.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/cli/tui/widgets/message.py tests/test_tui_widgets.py
git commit -m "feat: add MessageWidget with markdown rendering"
```

---

### Task 6: AgentCard widget（agent 状态卡片）

**Files:**
- Create: `src/duckagent/cli/tui/widgets/agent_card.py`
- Modify: `tests/test_tui_widgets.py`

- [ ] **Step 1: 写测试**

在 `tests/test_tui_widgets.py` 中添加：

```python
from duckagent.cli.tui.widgets.agent_card import AgentCard


class AgentCardTestApp(App):
    def compose(self) -> ComposeResult:
        yield AgentCard(agent_id="main_agent")
        yield AgentCard(agent_id="trace_agent")


@pytest.mark.asyncio
async def test_agent_card_initial_state():
    app = AgentCardTestApp()
    async with app.run_test() as pilot:
        cards = app.query(AgentCard)
        assert len(list(cards)) == 2


@pytest.mark.asyncio
async def test_agent_card_update_status():
    app = AgentCardTestApp()
    async with app.run_test() as pilot:
        card = app.query(AgentCard).first()
        card.update_status("thinking", task_summary="分析加密算法")
        assert card.state == "thinking"
        assert "分析加密算法" in card.task_summary
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_tui_widgets.py::test_agent_card_initial_state -v`
Expected: FAIL

- [ ] **Step 3: 实现 AgentCard**

`src/duckagent/cli/tui/widgets/agent_card.py`:

```python
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
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_tui_widgets.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/cli/tui/widgets/agent_card.py tests/test_tui_widgets.py
git commit -m "feat: add AgentCard widget with reactive status"
```

---

### Task 7: DuckApp 主类 + CSS 布局

**Files:**
- Create: `src/duckagent/cli/tui/app.py`
- Create: `src/duckagent/cli/tui/app.tcss`

- [ ] **Step 1: 创建 Textual CSS 布局文件**

`src/duckagent/cli/tui/app.tcss`:

```css
Screen {
    layout: grid;
    grid-size: 2 2;
    grid-columns: 7fr 3fr;
    grid-rows: 1fr auto;
}

#messages {
    row-span: 1;
    column-span: 1;
    border: solid $surface-lighten-2;
    padding: 1;
}

#agents {
    row-span: 1;
    column-span: 1;
    border: solid $surface-lighten-2;
    padding: 1;
}

InputArea {
    column-span: 2;
}
```

- [ ] **Step 2: 实现 DuckApp 骨架（无 agent 启动，纯 UI）**

`src/duckagent/cli/tui/app.py`:

```python
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header

from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.input_area import InputArea
from duckagent.cli.tui.widgets.message import MessageWidget


class DuckApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "DuckAgent"
    BINDINGS = [
        ("ctrl+l", "clear_messages", "清屏"),
        ("ctrl+c", "quit", "退出"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="messages")
        yield VerticalScroll(id="agents")
        yield InputArea()
        yield Footer()

    def on_mount(self) -> None:
        agents_panel = self.query_one("#agents", VerticalScroll)
        agents_panel.mount(AgentCard(agent_id="main_agent"))
        agents_panel.mount(AgentCard(agent_id="trace_agent"))

    def action_clear_messages(self) -> None:
        container = self.query_one("#messages", VerticalScroll)
        container.remove_children()
```

- [ ] **Step 3: 写冒烟测试**

在 `tests/test_tui_widgets.py` 中添加：

```python
from duckagent.cli.tui.app import DuckApp


@pytest.mark.asyncio
async def test_duck_app_mounts():
    app = DuckApp()
    async with app.run_test() as pilot:
        assert app.query_one("#messages") is not None
        assert app.query_one("#agents") is not None
        assert app.query_one(InputArea) is not None
        cards = list(app.query(AgentCard))
        assert len(cards) == 2
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/test_tui_widgets.py::test_duck_app_mounts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/cli/tui/app.py src/duckagent/cli/tui/app.tcss tests/test_tui_widgets.py
git commit -m "feat: add DuckApp skeleton with panel layout"
```

---

### Task 8: Bus worker（消息消费 → UI 更新）

**Files:**
- Create: `src/duckagent/cli/tui/worker.py`
- Modify: `src/duckagent/cli/tui/app.py`

- [ ] **Step 1: 实现 worker 模块**

`src/duckagent/cli/tui/worker.py`:

```python
import asyncio
import json

from textual.app import App
from textual.containers import VerticalScroll

from duckagent.bus.models import Message
from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.message import MessageWidget


async def consume_human_queue(app: App, queue: asyncio.Queue[Message]) -> None:
    while True:
        msg = await queue.get()
        if msg.type == "status":
            _handle_status(app, msg)
        else:
            _handle_message(app, msg)


def _handle_message(app: App, msg: Message) -> None:
    container = app.query_one("#messages", VerticalScroll)
    widget = MessageWidget(msg)
    app.call_from_thread(container.mount, widget)
    app.call_from_thread(container.scroll_end)


def _handle_status(app: App, msg: Message) -> None:
    try:
        data = json.loads(msg.content)
    except json.JSONDecodeError:
        return
    for card in app.query(AgentCard):
        if card.agent_id == msg.from_agent:
            app.call_from_thread(
                card.update_status,
                state=data.get("state", "idle"),
                task_summary=data.get("task_summary", ""),
                last_conclusion=data.get("last_conclusion", ""),
            )
            break
```

- [ ] **Step 2: 集成 worker 到 DuckApp**

修改 `src/duckagent/cli/tui/app.py`，在 `on_mount` 中订阅 bus 并启动 worker：

```python
import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header

from duckagent.bus import MessageBus, Message
from duckagent.agents.main_agent import MainAgent
from duckagent.agents.trace_agent import TraceAgent
from duckagent.config import settings
from duckagent.cli.tui.widgets.agent_card import AgentCard
from duckagent.cli.tui.widgets.input_area import InputArea
from duckagent.cli.tui.widgets.message import MessageWidget
from duckagent.cli.tui.worker import consume_human_queue


class DuckApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "DuckAgent"
    BINDINGS = [
        ("ctrl+l", "clear_messages", "清屏"),
        ("ctrl+c", "quit", "退出"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._bus: MessageBus | None = None
        self._main_agent: MainAgent | None = None
        self._trace_agent: TraceAgent | None = None
        self._worker_task: asyncio.Task | None = None

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
        tui_queue = self._bus.subscribe("_tui")

        self._worker_task = asyncio.create_task(consume_human_queue(self, human_queue))
        self._status_task = asyncio.create_task(self._consume_status(tui_queue))

    async def _consume_status(self, queue: asyncio.Queue) -> None:
        """Consume status messages for agent card updates."""
        import json
        while True:
            msg = await queue.get()
            if msg.type != "status":
                continue
            try:
                data = json.loads(msg.content)
            except Exception:
                continue
            for card in self.query(AgentCard):
                if card.agent_id == msg.from_agent:
                    card.update_status(
                        state=data.get("state", "idle"),
                        task_summary=data.get("task_summary", ""),
                        last_conclusion=data.get("last_conclusion", ""),
                    )
                    break

    async def on_unmount(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
        if hasattr(self, "_status_task") and self._status_task:
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
        container.scroll_end()
        asyncio.create_task(self._bus.publish(msg))

    def action_clear_messages(self) -> None:
        container = self.query_one("#messages", VerticalScroll)
        container.remove_children()
```

- [ ] **Step 3: 运行冒烟测试**

Run: `uv run pytest tests/test_tui_widgets.py::test_duck_app_mounts -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/duckagent/cli/tui/worker.py src/duckagent/cli/tui/app.py
git commit -m "feat: integrate bus worker and agent lifecycle into DuckApp"
```

---

### Task 9: 接入 typer CLI 入口

**Files:**
- Modify: `src/duckagent/cli/app.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 修改 cli/app.py 的 run 命令**

替换 `src/duckagent/cli/app.py` 中的 `run` 命令和所有 `_run_interactive` 相关代码：

```python
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import typer
import structlog

from duckagent.bus import Message, MessageBus
from duckagent.config import settings

logger = structlog.get_logger()
app = typer.Typer(name="duck", help="DuckAgent - Android 逆向 Multi-Agent 系统")


@asynccontextmanager
async def get_bus():
    bus = MessageBus(db_path=settings.db_path)
    await bus.initialize()
    try:
        yield bus
    finally:
        await bus.close()


def format_message(msg: Message) -> str:
    ts = msg.timestamp.strftime("%H:%M") if isinstance(msg.timestamp, datetime) else str(msg.timestamp)[:5]
    target = msg.to_agent or "all"
    if target == "human":
        target = "you"
    return f"[{ts}] {msg.from_agent} → {target}: {msg.content}"


@app.command()
def run():
    """启动 TUI 交互模式"""
    from duckagent.cli.tui.app import DuckApp
    duck_app = DuckApp()
    duck_app.run()


@app.command()
def log(
    from_agent: str = typer.Option(None, "--from", help="按发送者过滤"),
    limit: int = typer.Option(50, "--limit", help="消息数量限制"),
    msg_type: str = typer.Option(None, "--type", help="按消息类型过滤"),
):
    """查看消息历史"""
    asyncio.run(_show_log(from_agent, limit, msg_type))


@app.command()
def send(message: str):
    """发送消息给主 Agent（非交互模式）"""
    asyncio.run(_send_message(message))


async def _show_log(from_agent: str | None, limit: int, msg_type: str | None):
    async with get_bus() as bus:
        history = await bus.get_history(
            limit=limit, from_agent=from_agent, msg_type=msg_type
        )
        if not history:
            typer.echo("没有消息")
            return
        for msg in history:
            typer.echo(format_message(msg))


async def _send_message(content: str):
    async with get_bus() as bus:
        msg = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content=content,
            evidence=[],
            confidence="high",
        )
        await bus.publish(msg)
        typer.echo(f"已发送: {content}")
```

- [ ] **Step 2: 更新 CLI 测试**

修改 `tests/test_cli.py`，移除对已删除函数的 mock：

```python
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock

from duckagent.cli.app import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "log" in result.stdout
    assert "send" in result.stdout


def test_cli_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "TUI" in result.stdout or "交互" in result.stdout


def test_cli_log_help():
    result = runner.invoke(app, ["log", "--help"])
    assert result.exit_code == 0
    assert "--from" in result.stdout
    assert "--limit" in result.stdout
    assert "--type" in result.stdout


def test_cli_send_help():
    result = runner.invoke(app, ["send", "--help"])
    assert result.exit_code == 0


@patch("duckagent.cli.app._show_log", new_callable=AsyncMock)
def test_cli_log_invokes_show_log(mock_show_log):
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0


@patch("duckagent.cli.app._send_message", new_callable=AsyncMock)
def test_cli_send_invokes_send_message(mock_send):
    result = runner.invoke(app, ["send", "hello agent"])
    assert result.exit_code == 0
```

- [ ] **Step 3: 运行全部测试**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/duckagent/cli/app.py tests/test_cli.py
git commit -m "feat: replace interactive CLI with Textual TUI entry point"
```

---

### Task 10: 安装依赖 + 端到端验证

**Files:**
- No new files

- [ ] **Step 1: 安装依赖**

Run: `uv sync`
Expected: textual 安装成功

- [ ] **Step 2: 运行全部测试套件**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: 手动启动 TUI 验证**

Run: `uv run duck run`
Expected: Textual TUI 启动，显示面板布局（左侧消息区、右侧 agent 卡片、底部输入框）

- [ ] **Step 4: 验证输入和消息流**

在 TUI 中输入一条消息，确认：
- 消息出现在左侧面板（markdown 渲染）
- agent 状态卡片更新为 thinking
- 收到回复后 markdown 正确渲染
- agent 状态回到 idle

- [ ] **Step 5: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: adjustments from e2e testing"
```
