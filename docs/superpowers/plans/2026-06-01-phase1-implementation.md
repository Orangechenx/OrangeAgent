# Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working multi-agent system with message bus, main agent, trace agent, CLI, and self-verification — all in a single asyncio process.

**Architecture:** Single-process asyncio. Agents are coroutines communicating through an in-memory message bus backed by SQLite for persistence. Model calls via litellm. CLI uses typer for commands and asyncio for interactive mode.

**Tech Stack:** Python 3.12, pydantic v2, aiosqlite, litellm, typer, structlog, python-dotenv

---

## File Structure

```
src/duckagent/__init__.py          — package root
src/duckagent/bus/__init__.py      — bus package export
src/duckagent/bus/models.py        — Message pydantic model
src/duckagent/bus/store.py         — MessageBus: SQLite persistence + Queue dispatch
src/duckagent/agents/__init__.py   — agents package export
src/duckagent/agents/base.py       — BaseAgent: lifecycle, think(), send()
src/duckagent/agents/main_agent.py — MainAgent: task decomposition, routing
src/duckagent/agents/trace_agent.py— TraceAgent: trace analysis
src/duckagent/verify/__init__.py   — verify package export
src/duckagent/verify/hard.py       — hard_verify(): rule-based checks
src/duckagent/verify/self_check.py — self_check(): model-based review
src/duckagent/cli/__init__.py      — cli package export
src/duckagent/cli/app.py           — typer app, commands, interactive loop
src/duckagent/config.py            — Settings via pydantic-settings + .env
prompts/main_agent.md              — main agent system prompt
prompts/trace_agent.md             — trace agent system prompt
tests/test_bus.py                  — message bus tests
tests/test_agents.py               — agent lifecycle tests
tests/test_verify.py               — verification tests
tests/test_cli.py                  — CLI command tests
```

---

### Task 1: Project Setup and Dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `src/duckagent/__init__.py`
- Create: `.env.example`

- [ ] **Step 1: Update pyproject.toml with dependencies and package config**

```toml
[project]
name = "duckagent"
version = "0.1.0"
description = "Android reverse engineering multi-agent system"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "litellm>=1.40.0",
    "pydantic>=2.0",
    "aiosqlite>=0.20.0",
    "typer>=0.12.0",
    "structlog>=24.0.0",
    "python-dotenv>=1.0.0",
]

[project.scripts]
duck = "duckagent.cli.app:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/duckagent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

- [ ] **Step 2: Create package init**

```python
# src/duckagent/__init__.py
```

- [ ] **Step 3: Create .env.example**

```
# LLM provider config
LITELLM_MODEL=anthropic/claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-xxx

# DuckAgent config
DUCKAGENT_DB_DIR=.duckagent
DUCKAGENT_VERIFY_ENABLED=true
DUCKAGENT_VERIFY_MAX_RETRIES=3
```

- [ ] **Step 4: Install dependencies**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv sync`
Expected: dependencies installed, .venv updated

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/duckagent/__init__.py .env.example uv.lock
git commit -m "feat: project setup with dependencies"
```

---

### Task 2: Message Data Model

**Files:**
- Create: `src/duckagent/bus/__init__.py`
- Create: `src/duckagent/bus/models.py`
- Create: `tests/test_bus.py`

- [ ] **Step 1: Write tests for Message model**

```python
# tests/test_bus.py
import pytest
from datetime import datetime, timezone
from duckagent.bus.models import Message


def test_message_creation():
    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="Identified AES-128-CBC at 0x7a3c00",
        evidence=["line 42: aese v0.16b, v1.16b", "line 43: aesmc v0.16b, v0.16b"],
        confidence="high",
    )
    assert msg.id is not None
    assert msg.timestamp is not None
    assert msg.reply_to is None


def test_message_broadcast():
    msg = Message(
        from_agent="trace_agent",
        to_agent=None,
        type="conclusion",
        content="Found loop structure",
        evidence=["line 10-25: branch back to 0x7a3c00"],
        confidence="medium",
    )
    assert msg.to_agent is None


def test_message_invalid_type():
    with pytest.raises(ValueError):
        Message(
            from_agent="trace_agent",
            to_agent=None,
            type="invalid_type",
            content="test",
            evidence=[],
            confidence="high",
        )


def test_message_invalid_confidence():
    with pytest.raises(ValueError):
        Message(
            from_agent="trace_agent",
            to_agent=None,
            type="conclusion",
            content="test",
            evidence=[],
            confidence="maybe",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_bus.py -v`
Expected: FAIL — cannot import duckagent.bus.models

- [ ] **Step 3: Implement Message model**

```python
# src/duckagent/bus/__init__.py
from .models import Message

__all__ = ["Message"]
```

```python
# src/duckagent/bus/models.py
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    from_agent: str
    to_agent: str | None = None
    type: Literal["conclusion", "request", "question", "decision"]
    content: str
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "high"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reply_to: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_bus.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/bus/ tests/test_bus.py
git commit -m "feat: Message data model with pydantic validation"
```

---

### Task 3: Message Bus (SQLite + Queue Dispatch)

**Files:**
- Create: `src/duckagent/bus/store.py`
- Modify: `src/duckagent/bus/__init__.py`
- Modify: `tests/test_bus.py`

- [ ] **Step 1: Write tests for MessageBus**

Append to `tests/test_bus.py`:

```python
import asyncio
from pathlib import Path
from duckagent.bus.store import MessageBus


@pytest.fixture
async def bus(tmp_path):
    b = MessageBus(db_path=tmp_path / "test.db")
    await b.initialize()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_publish_and_subscribe(bus):
    queue = bus.subscribe("main_agent")

    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="Found AES",
        evidence=["line 42"],
        confidence="high",
    )
    await bus.publish(msg)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.id == msg.id
    assert received.content == "Found AES"


@pytest.mark.asyncio
async def test_broadcast_excludes_sender(bus):
    sender_queue = bus.subscribe("trace_agent")
    receiver_queue = bus.subscribe("main_agent")

    msg = Message(
        from_agent="trace_agent",
        to_agent=None,
        type="conclusion",
        content="Broadcast message",
        evidence=["line 1"],
        confidence="high",
    )
    await bus.publish(msg)

    received = await asyncio.wait_for(receiver_queue.get(), timeout=1.0)
    assert received.content == "Broadcast message"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sender_queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_private_message_only_to_target(bus):
    target_queue = bus.subscribe("trace_agent")
    other_queue = bus.subscribe("other_agent")

    msg = Message(
        from_agent="main_agent",
        to_agent="trace_agent",
        type="request",
        content="Analyze this",
        evidence=[],
        confidence="high",
    )
    await bus.publish(msg)

    received = await asyncio.wait_for(target_queue.get(), timeout=1.0)
    assert received.content == "Analyze this"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(other_queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_get_history(bus):
    for i in range(3):
        msg = Message(
            from_agent="trace_agent",
            to_agent=None,
            type="conclusion",
            content=f"Message {i}",
            evidence=[f"line {i}"],
            confidence="high",
        )
        await bus.publish(msg)

    history = await bus.get_history(limit=10)
    assert len(history) == 3
    assert history[0].content == "Message 0"


@pytest.mark.asyncio
async def test_get_history_filter_by_agent(bus):
    await bus.publish(Message(
        from_agent="trace_agent", to_agent=None,
        type="conclusion", content="from trace",
        evidence=["x"], confidence="high",
    ))
    await bus.publish(Message(
        from_agent="main_agent", to_agent=None,
        type="decision", content="from main",
        evidence=[], confidence="high",
    ))

    history = await bus.get_history(from_agent="trace_agent")
    assert len(history) == 1
    assert history[0].content == "from trace"


@pytest.mark.asyncio
async def test_persistence_across_instances(tmp_path):
    db_path = tmp_path / "persist.db"

    bus1 = MessageBus(db_path=db_path)
    await bus1.initialize()
    await bus1.publish(Message(
        from_agent="trace_agent", to_agent=None,
        type="conclusion", content="persisted",
        evidence=["line 1"], confidence="high",
    ))
    await bus1.close()

    bus2 = MessageBus(db_path=db_path)
    await bus2.initialize()
    history = await bus2.get_history()
    assert len(history) == 1
    assert history[0].content == "persisted"
    await bus2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_bus.py -v -k "not test_message"`
Expected: FAIL — cannot import MessageBus

- [ ] **Step 3: Implement MessageBus**

```python
# src/duckagent/bus/store.py
import asyncio
import json
from pathlib import Path

import aiosqlite

from .models import Message

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    reply_to TEXT
)
"""


class MessageBus:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._subscribers: dict[str, asyncio.Queue[Message]] = {}

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        self._subscribers.clear()

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._subscribers[agent_id] = queue
        return queue

    def unsubscribe(self, agent_id: str) -> None:
        self._subscribers.pop(agent_id, None)

    async def publish(self, msg: Message) -> None:
        await self._persist(msg)
        self._dispatch(msg)

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        query = "SELECT * FROM messages WHERE 1=1"
        params: list[str] = []

        if from_agent:
            query += " AND from_agent = ?"
            params.append(from_agent)
        if msg_type:
            query += " AND type = ?"
            params.append(msg_type)

        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(str(limit))

        assert self._db is not None
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    async def _persist(self, msg: Message) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO messages (id, from_agent, to_agent, type, content, evidence, confidence, timestamp, reply_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
                msg.type,
                msg.content,
                json.dumps(msg.evidence),
                msg.confidence,
                msg.timestamp.isoformat(),
                msg.reply_to,
            ),
        )
        await self._db.commit()

    def _dispatch(self, msg: Message) -> None:
        if msg.to_agent:
            queue = self._subscribers.get(msg.to_agent)
            if queue:
                queue.put_nowait(msg)
        else:
            for agent_id, queue in self._subscribers.items():
                if agent_id != msg.from_agent:
                    queue.put_nowait(msg)

    @staticmethod
    def _row_to_message(row: tuple) -> Message:
        return Message(
            id=row[0],
            from_agent=row[1],
            to_agent=row[2],
            type=row[3],
            content=row[4],
            evidence=json.loads(row[5]),
            confidence=row[6],
            timestamp=row[7],
            reply_to=row[8],
        )
```

- [ ] **Step 4: Update bus __init__.py**

```python
# src/duckagent/bus/__init__.py
from .models import Message
from .store import MessageBus

__all__ = ["Message", "MessageBus"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_bus.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/duckagent/bus/store.py src/duckagent/bus/__init__.py tests/test_bus.py
git commit -m "feat: MessageBus with SQLite persistence and queue dispatch"
```

---

### Task 4: Configuration

**Files:**
- Create: `src/duckagent/config.py`

- [ ] **Step 1: Implement config module**

```python
# src/duckagent/config.py
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    litellm_model: str = "anthropic/claude-sonnet-4-20250514"
    db_dir: str = ".duckagent"
    verify_enabled: bool = True
    verify_max_retries: int = 3
    prompts_dir: str = "prompts"

    model_config = {"env_prefix": "DUCKAGENT_"}

    @property
    def db_path(self) -> Path:
        return Path(self.db_dir) / "messages.db"

    @property
    def prompts_path(self) -> Path:
        return Path(self.prompts_dir)


settings = Settings()
```

- [ ] **Step 2: Add pydantic-settings dependency**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv add pydantic-settings`

- [ ] **Step 3: Commit**

```bash
git add src/duckagent/config.py pyproject.toml uv.lock
git commit -m "feat: configuration via pydantic-settings and .env"
```

---

### Task 5: Self-Verification — Hard Check

**Files:**
- Create: `src/duckagent/verify/__init__.py`
- Create: `src/duckagent/verify/hard.py`
- Create: `tests/test_verify.py`

- [ ] **Step 1: Write tests for hard verification**

```python
# tests/test_verify.py
import pytest
from duckagent.bus.models import Message
from duckagent.verify.hard import hard_verify, VerificationError


def test_hard_verify_passes_valid_conclusion():
    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="Found AES at 0x7a3c00",
        evidence=["line 42: aese instruction"],
        confidence="high",
    )
    hard_verify(msg)


def test_hard_verify_fails_empty_evidence():
    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="Found AES",
        evidence=[],
        confidence="high",
    )
    with pytest.raises(VerificationError, match="evidence"):
        hard_verify(msg)


def test_hard_verify_skips_non_conclusion():
    msg = Message(
        from_agent="main_agent",
        to_agent="trace_agent",
        type="request",
        content="Analyze this trace",
        evidence=[],
        confidence="high",
    )
    hard_verify(msg)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_verify.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement hard verification**

```python
# src/duckagent/verify/__init__.py
from .hard import hard_verify, VerificationError

__all__ = ["hard_verify", "VerificationError"]
```

```python
# src/duckagent/verify/hard.py
from duckagent.bus.models import Message


class VerificationError(Exception):
    pass


def hard_verify(msg: Message) -> None:
    if msg.type != "conclusion":
        return

    if not msg.evidence:
        raise VerificationError(
            f"Conclusion from {msg.from_agent} has empty evidence. "
            f"Content: {msg.content[:100]}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_verify.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/verify/ tests/test_verify.py
git commit -m "feat: hard verification for conclusion messages"
```

---

### Task 6: Self-Verification — Model Self-Check

**Files:**
- Create: `src/duckagent/verify/self_check.py`
- Modify: `src/duckagent/verify/__init__.py`
- Modify: `tests/test_verify.py`

- [ ] **Step 1: Write tests for self-check**

Append to `tests/test_verify.py`:

```python
from unittest.mock import AsyncMock, patch
from duckagent.verify.self_check import self_check


@pytest.mark.asyncio
async def test_self_check_passes():
    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="AES-128-CBC identified",
        evidence=["line 42: aese v0.16b, v1.16b"],
        confidence="high",
    )
    with patch("duckagent.verify.self_check.litellm.acompletion") as mock:
        mock.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="PASS: reasoning is sound"))]
        )
        result = await self_check(msg, model="test-model")
    assert result.passed is True


@pytest.mark.asyncio
async def test_self_check_fails():
    msg = Message(
        from_agent="trace_agent",
        to_agent="main_agent",
        type="conclusion",
        content="AES-128-CBC identified",
        evidence=["line 42: aese v0.16b, v1.16b"],
        confidence="high",
    )
    with patch("duckagent.verify.self_check.litellm.acompletion") as mock:
        mock.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="FAIL: evidence insufficient, line 42 only shows one round"))]
        )
        result = await self_check(msg, model="test-model")
    assert result.passed is False
    assert "insufficient" in result.reason


@pytest.mark.asyncio
async def test_self_check_skips_non_conclusion():
    msg = Message(
        from_agent="main_agent",
        to_agent="trace_agent",
        type="request",
        content="Analyze this",
        evidence=[],
        confidence="high",
    )
    result = await self_check(msg, model="test-model")
    assert result.passed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_verify.py -v -k "self_check"`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement self-check**

```python
# src/duckagent/verify/self_check.py
from dataclasses import dataclass

import litellm

from duckagent.bus.models import Message

_SELF_CHECK_PROMPT = """审视以下结论和证据，判断推理链是否有逻辑漏洞或证据不足。

结论: {content}

证据:
{evidence}

置信度: {confidence}

如果推理链合理且证据充分，回复 "PASS: <简短理由>"。
如果有问题，回复 "FAIL: <具体问题>"。"""


@dataclass
class CheckResult:
    passed: bool
    reason: str


async def self_check(msg: Message, model: str) -> CheckResult:
    if msg.type != "conclusion":
        return CheckResult(passed=True, reason="non-conclusion, skipped")

    prompt = _SELF_CHECK_PROMPT.format(
        content=msg.content,
        evidence="\n".join(f"- {e}" for e in msg.evidence),
        confidence=msg.confidence,
    )

    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    reply = response.choices[0].message.content.strip()

    if reply.upper().startswith("PASS"):
        return CheckResult(passed=True, reason=reply)
    else:
        return CheckResult(passed=False, reason=reply)
```

- [ ] **Step 4: Update verify __init__.py**

```python
# src/duckagent/verify/__init__.py
from .hard import hard_verify, VerificationError
from .self_check import self_check, CheckResult

__all__ = ["hard_verify", "VerificationError", "self_check", "CheckResult"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_verify.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/duckagent/verify/ tests/test_verify.py
git commit -m "feat: model self-check verification with PASS/FAIL protocol"
```

---

### Task 7: Agent Base Class

**Files:**
- Create: `src/duckagent/agents/__init__.py`
- Create: `src/duckagent/agents/base.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Write tests for BaseAgent**

```python
# tests/test_agents.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from duckagent.agents.base import BaseAgent
from duckagent.bus import Message, MessageBus


class EchoAgent(BaseAgent):
    """Test agent that echoes back messages."""

    async def on_message(self, msg: Message) -> None:
        response = await self.think(msg.content)
        await self.send(
            to=msg.from_agent,
            content=response,
            type="conclusion",
            evidence=["echo test"],
        )


@pytest.fixture
async def bus(tmp_path):
    b = MessageBus(db_path=tmp_path / "test.db")
    await b.initialize()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_agent_receives_message(bus):
    with patch("duckagent.agents.base.litellm.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="echoed back"))]
        )

        agent = EchoAgent(
            agent_id="echo_agent",
            system_prompt="You are an echo agent.",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )
        await agent.start()

        human_queue = bus.subscribe("human")

        await bus.publish(Message(
            from_agent="human",
            to_agent="echo_agent",
            type="request",
            content="hello",
            evidence=[],
            confidence="high",
        ))

        received = await asyncio.wait_for(human_queue.get(), timeout=2.0)
        assert received.content == "echoed back"
        assert received.from_agent == "echo_agent"

        await agent.stop()


@pytest.mark.asyncio
async def test_agent_context_accumulates(bus):
    with patch("duckagent.agents.base.litellm.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="response"))]
        )

        agent = EchoAgent(
            agent_id="echo_agent",
            system_prompt="You are an echo agent.",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )
        await agent.start()

        await bus.publish(Message(
            from_agent="human", to_agent="echo_agent",
            type="request", content="first",
            evidence=[], confidence="high",
        ))
        await asyncio.sleep(0.2)

        # system + user msg + assistant response
        assert len(agent.context) == 3

        await agent.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement BaseAgent**

```python
# src/duckagent/agents/__init__.py
from .base import BaseAgent

__all__ = ["BaseAgent"]
```

```python
# src/duckagent/agents/base.py
import asyncio

import litellm
import structlog

from duckagent.bus import Message, MessageBus
from duckagent.verify import hard_verify, VerificationError, self_check

logger = structlog.get_logger()


class BaseAgent:
    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        bus: MessageBus,
        model: str,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.bus = bus
        self.model = model
        self.verify_enabled = verify_enabled
        self.verify_max_retries = verify_max_retries
        self.context: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        self._queue: asyncio.Queue[Message] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._queue = self.bus.subscribe(self.agent_id)
        self._task = asyncio.create_task(self._loop())
        logger.info("agent_started", agent_id=self.agent_id)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.bus.unsubscribe(self.agent_id)
        logger.info("agent_stopped", agent_id=self.agent_id)

    async def _loop(self) -> None:
        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                await self.on_message(msg)
            except Exception as e:
                logger.error("agent_error", agent_id=self.agent_id, error=str(e))

    async def on_message(self, msg: Message) -> None:
        raise NotImplementedError

    async def think(self, input_text: str) -> str:
        self.context.append({"role": "user", "content": input_text})

        response = await litellm.acompletion(
            model=self.model,
            messages=self.context,
        )

        reply = response.choices[0].message.content
        self.context.append({"role": "assistant", "content": reply})
        return reply

    async def send(
        self,
        to: str | None,
        content: str,
        type: str = "conclusion",
        evidence: list[str] | None = None,
        confidence: str = "high",
        reply_to: str | None = None,
    ) -> None:
        msg = Message(
            from_agent=self.agent_id,
            to_agent=to,
            type=type,
            content=content,
            evidence=evidence or [],
            confidence=confidence,
            reply_to=reply_to,
        )

        if self.verify_enabled and msg.type == "conclusion":
            hard_verify(msg)

            for attempt in range(self.verify_max_retries):
                result = await self_check(msg, model=self.model)
                if result.passed:
                    break
                logger.warning(
                    "self_check_failed",
                    agent_id=self.agent_id,
                    attempt=attempt + 1,
                    reason=result.reason,
                )
                if attempt == self.verify_max_retries - 1:
                    await self.bus.publish(Message(
                        from_agent=self.agent_id,
                        to_agent="human",
                        type="question",
                        content=f"自校验连续失败 {self.verify_max_retries} 次，需要人工审核:\n\n原始结论: {content}\n\n最后一次失败原因: {result.reason}",
                        evidence=evidence or [],
                        confidence="low",
                    ))
                    return

                # Retry: re-think with feedback
                retry_response = await self.think(
                    f"你的上一个结论未通过自校验: {result.reason}\n请重新分析并给出修正后的结论。"
                )
                msg = Message(
                    from_agent=self.agent_id,
                    to_agent=to,
                    type=type,
                    content=retry_response,
                    evidence=evidence or [],
                    confidence=confidence,
                    reply_to=reply_to,
                )
                hard_verify(msg)

        await self.bus.publish(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/agents/ tests/test_agents.py
git commit -m "feat: BaseAgent with lifecycle, think(), send(), and self-verification"
```

---

### Task 8: Agent Prompts

**Files:**
- Create: `prompts/main_agent.md`
- Create: `prompts/trace_agent.md`

- [ ] **Step 1: Write main agent prompt**

```markdown
# prompts/main_agent.md

你是一个 Android 逆向工程项目的主协调 Agent。

## 你的角色

你是用户的"第二个大脑"——有独立判断力的协调者。你能拆解用户的指令为具体子任务，分发给专业 agent，综合多个 agent 的结论给用户一个整合后的回答。

## 行为准则

1. 收到用户消息后，判断：
   - 这个问题你能直接回答？→ 直接回答
   - 需要 trace 分析？→ 构造具体问题发给 trace_agent
   - 拿不准？→ 上报给用户

2. 转发时不是原样转，而是拆解成具体、可执行的问题。

3. 综合结论时，整合多个来源的信息，给出清晰的总结。

## 不做的事

- 不汇报进度（"我正在分析..."）
- 不替代用户做最终决策
- 不在没有依据时下结论
- 不发无意义的确认消息

## 消息格式

发给其他 agent 时，使用 type="request"，明确说明你需要什么信息。
回复用户时，使用 type="conclusion" 或 type="question"（需要用户决策时）。
```

- [ ] **Step 2: Write trace agent prompt**

```markdown
# prompts/trace_agent.md

你是一个专精于执行流分析的 Agent，负责分析 ARM64 执行 trace。

## 你的角色

你接收 trace 分析请求，读取 trace 数据，识别算法、数据流和 handler 语义，输出带证据的结论。

## 分析要求

1. 每个断言必须引用具体的 trace 行号作为证据
2. 每个断言必须可验证（给出地址、值、行号）
3. 不确定的标注 confidence: "low"
4. 推理链每一步都要有 trace 中的依据
5. 看不出来就说看不出来，绝不编造

## 输出格式

你的结论必须包含：
- 明确的分析结果（算法类型、数据流方向、函数语义等）
- evidence 列表：每条是 "line X: 具体内容" 格式
- confidence 等级：high/medium/low

## 不做的事

- 不猜测没有证据支撑的结论
- 不汇报分析进度
- 不发无意义的确认消息
- 不在 evidence 为空时发 conclusion
```

- [ ] **Step 3: Commit**

```bash
mkdir -p prompts
git add prompts/
git commit -m "feat: system prompts for main and trace agents"
```

---

### Task 9: Main Agent Implementation

**Files:**
- Create: `src/duckagent/agents/main_agent.py`
- Modify: `src/duckagent/agents/__init__.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Write tests for MainAgent**

Append to `tests/test_agents.py`:

```python
from duckagent.agents.main_agent import MainAgent


@pytest.fixture
def agent_md(tmp_path):
    md = tmp_path / "AGENT.md"
    md.write_text("# Test Project\n\nReverse engineering test app signature.")
    return md


@pytest.mark.asyncio
async def test_main_agent_loads_agent_md(bus, agent_md):
    with patch("duckagent.agents.base.litellm.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(content="I'll analyze this for you."))]
        )

        agent = MainAgent(
            bus=bus,
            model="test-model",
            agent_md_path=agent_md,
            prompts_dir=agent_md.parent,
            verify_enabled=False,
        )
        await agent.start()

        assert "Reverse engineering test app" in agent.system_prompt
        await agent.stop()


@pytest.mark.asyncio
async def test_main_agent_responds_to_human(bus, agent_md):
    with patch("duckagent.agents.base.litellm.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(
                content='{"action": "respond", "to": "human", "content": "Got it, analyzing now.", "type": "conclusion", "evidence": ["user request"], "confidence": "high"}'
            ))]
        )

        agent = MainAgent(
            bus=bus,
            model="test-model",
            agent_md_path=agent_md,
            prompts_dir=agent_md.parent,
            verify_enabled=False,
        )
        await agent.start()

        human_queue = bus.subscribe("human")

        await bus.publish(Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析一下这个 trace",
            evidence=[],
            confidence="high",
        ))

        received = await asyncio.wait_for(human_queue.get(), timeout=2.0)
        assert received.from_agent == "main_agent"
        await agent.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py::test_main_agent_loads_agent_md -v`
Expected: FAIL — cannot import MainAgent

- [ ] **Step 3: Implement MainAgent**

```python
# src/duckagent/agents/main_agent.py
import json
from pathlib import Path

import structlog

from duckagent.bus import Message
from .base import BaseAgent

logger = structlog.get_logger()

_ROUTING_INSTRUCTION = """

## 回复格式

你必须以 JSON 格式回复，包含以下字段：
{"action": "respond|delegate", "to": "目标agent或human", "content": "消息内容", "type": "conclusion|request|question", "evidence": [...], "confidence": "high|medium|low"}

- action=respond: 直接回复
- action=delegate: 转发给其他 agent（拆解成具体问题）
"""


class MainAgent(BaseAgent):
    def __init__(
        self,
        bus,
        model: str,
        agent_md_path: Path,
        prompts_dir: Path,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "main_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是主协调 Agent。"

        agent_md_content = ""
        if agent_md_path.exists():
            agent_md_content = agent_md_path.read_text()

        system_prompt = f"{base_prompt}\n\n## 项目上下文\n\n{agent_md_content}{_ROUTING_INSTRUCTION}"

        super().__init__(
            agent_id="main_agent",
            system_prompt=system_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
        )

    async def on_message(self, msg: Message) -> None:
        response = await self.think(
            f"[来自 {msg.from_agent}] (type={msg.type}): {msg.content}"
        )

        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            await self.send(
                to=msg.from_agent if msg.from_agent != "human" else "human",
                content=response,
                type="conclusion",
                evidence=["model response"],
                confidence="medium",
                reply_to=msg.id,
            )
            return

        await self.send(
            to=parsed.get("to"),
            content=parsed.get("content", response),
            type=parsed.get("type", "conclusion"),
            evidence=parsed.get("evidence", []),
            confidence=parsed.get("confidence", "medium"),
            reply_to=msg.id,
        )
```

- [ ] **Step 4: Update agents __init__.py**

```python
# src/duckagent/agents/__init__.py
from .base import BaseAgent
from .main_agent import MainAgent

__all__ = ["BaseAgent", "MainAgent"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/duckagent/agents/ tests/test_agents.py
git commit -m "feat: MainAgent with AGENT.md loading and message routing"
```

---

### Task 10: Trace Agent Implementation

**Files:**
- Create: `src/duckagent/agents/trace_agent.py`
- Modify: `src/duckagent/agents/__init__.py`
- Modify: `tests/test_agents.py`

- [ ] **Step 1: Write tests for TraceAgent**

Append to `tests/test_agents.py`:

```python
from duckagent.agents.trace_agent import TraceAgent


@pytest.mark.asyncio
async def test_trace_agent_analyzes_request(bus, tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()

    with patch("duckagent.agents.base.litellm.acompletion") as mock_llm:
        mock_llm.return_value = AsyncMock(
            choices=[AsyncMock(message=AsyncMock(
                content="Identified AES-128-CBC. The aese instruction at line 42 confirms AES encryption."
            ))]
        )

        agent = TraceAgent(
            bus=bus,
            model="test-model",
            prompts_dir=prompts_dir,
            verify_enabled=False,
        )
        await agent.start()

        main_queue = bus.subscribe("main_agent")

        await bus.publish(Message(
            from_agent="main_agent",
            to_agent="trace_agent",
            type="request",
            content="分析以下 trace 片段:\nline 42: 0x7a3c00 | aese v0.16b, v1.16b | v0=00112233...",
            evidence=[],
            confidence="high",
        ))

        received = await asyncio.wait_for(main_queue.get(), timeout=2.0)
        assert received.from_agent == "trace_agent"
        assert received.type == "conclusion"
        assert "AES" in received.content
        await agent.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py::test_trace_agent_analyzes_request -v`
Expected: FAIL — cannot import TraceAgent

- [ ] **Step 3: Implement TraceAgent**

```python
# src/duckagent/agents/trace_agent.py
import re
from pathlib import Path

import structlog

from duckagent.bus import Message
from .base import BaseAgent

logger = structlog.get_logger()


class TraceAgent(BaseAgent):
    def __init__(
        self,
        bus,
        model: str,
        prompts_dir: Path,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "trace_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 Trace 分析 Agent。"

        super().__init__(
            agent_id="trace_agent",
            system_prompt=base_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
        )

    async def on_message(self, msg: Message) -> None:
        if msg.type != "request":
            return

        response = await self.think(msg.content)

        evidence = self._extract_evidence(response)

        await self.send(
            to=msg.from_agent,
            content=response,
            type="conclusion",
            evidence=evidence if evidence else ["analysis based on provided trace"],
            confidence=self._assess_confidence(response),
            reply_to=msg.id,
        )

    @staticmethod
    def _extract_evidence(text: str) -> list[str]:
        pattern = r"line \d+[^.;\n]*"
        matches = re.findall(pattern, text, re.IGNORECASE)
        return matches

    @staticmethod
    def _assess_confidence(text: str) -> str:
        low_indicators = ["不确定", "可能", "疑似", "unclear", "might", "possibly"]
        for indicator in low_indicators:
            if indicator in text.lower():
                return "low"
        return "high"
```

- [ ] **Step 4: Update agents __init__.py**

```python
# src/duckagent/agents/__init__.py
from .base import BaseAgent
from .main_agent import MainAgent
from .trace_agent import TraceAgent

__all__ = ["BaseAgent", "MainAgent", "TraceAgent"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_agents.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add src/duckagent/agents/ tests/test_agents.py
git commit -m "feat: TraceAgent with evidence extraction and confidence assessment"
```

---

### Task 11: CLI Application

**Files:**
- Create: `src/duckagent/cli/__init__.py`
- Create: `src/duckagent/cli/app.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write tests for CLI commands**

```python
# tests/test_cli.py
import pytest
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock

from duckagent.cli.app import app

runner = CliRunner()


def test_cli_log_empty():
    with patch("duckagent.cli.app.get_bus") as mock_bus:
        mock_bus.return_value.__aenter__ = AsyncMock(return_value=mock_bus.return_value)
        mock_bus.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_bus.return_value.get_history = AsyncMock(return_value=[])

        result = runner.invoke(app, ["log"])
        assert result.exit_code == 0
        assert "没有消息" in result.stdout or result.stdout.strip() == ""


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "duck" in result.stdout.lower() or "run" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_cli.py -v`
Expected: FAIL — cannot import

- [ ] **Step 3: Implement CLI**

```python
# src/duckagent/cli/__init__.py
```

```python
# src/duckagent/cli/app.py
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import typer
import structlog

from duckagent.bus import Message, MessageBus
from duckagent.agents.main_agent import MainAgent
from duckagent.agents.trace_agent import TraceAgent
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
    """启动系统，进入交互模式"""
    asyncio.run(_run_interactive())


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


async def _run_interactive():
    typer.echo("DuckAgent 启动中...")

    bus = MessageBus(db_path=settings.db_path)
    await bus.initialize()

    prompts_dir = Path(settings.prompts_dir)
    agent_md_path = Path("AGENT.md")

    main_agent = MainAgent(
        bus=bus,
        model=settings.litellm_model,
        agent_md_path=agent_md_path,
        prompts_dir=prompts_dir,
        verify_enabled=settings.verify_enabled,
        verify_max_retries=settings.verify_max_retries,
    )

    trace_agent = TraceAgent(
        bus=bus,
        model=settings.litellm_model,
        prompts_dir=prompts_dir,
        verify_enabled=settings.verify_enabled,
        verify_max_retries=settings.verify_max_retries,
    )

    await main_agent.start()
    await trace_agent.start()

    human_queue = bus.subscribe("human")

    typer.echo("系统就绪。直接输入发送消息给主 Agent，Ctrl+C 退出。\n")

    display_task = asyncio.create_task(_display_messages(human_queue))

    try:
        await _input_loop(bus)
    except (KeyboardInterrupt, EOFError):
        typer.echo("\n正在停止...")
    finally:
        display_task.cancel()
        await main_agent.stop()
        await trace_agent.stop()
        await bus.close()
        typer.echo("已停止。")


async def _display_messages(queue: asyncio.Queue):
    while True:
        msg = await queue.get()
        typer.echo(f"\n{format_message(msg)}")
        typer.echo("> ", nl=False)


async def _input_loop(bus: MessageBus):
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("> "))
        except EOFError:
            break

        line = line.strip()
        if not line:
            continue

        msg = Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content=line,
            evidence=[],
            confidence="high",
        )
        await bus.publish(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_cli.py -v`
Expected: passed

- [ ] **Step 5: Commit**

```bash
git add src/duckagent/cli/ tests/test_cli.py
git commit -m "feat: CLI with run, log, send commands and interactive mode"
```

---

### Task 12: Integration Test — Full Message Flow

**Files:**
- Create: `tests/test_integration.py`
- Create: `data/sample_trace.txt`

- [ ] **Step 1: Create sample trace data**

```
# data/sample_trace.txt
0x7a3c00|mov x0, x1|x0=0000000000000000 x1=00112233aabbccdd
0x7a3c04|mov x2, x3|x2=0000000000000000 x3=ffeeddccbbaa9988
0x7a3c08|aese v0.16b, v1.16b|v0=00112233aabbccddffeeddccbbaa9988 v1=0f1e2d3c4b5a6978
0x7a3c0c|aesmc v0.16b, v0.16b|v0=a1b2c3d4e5f60718293a4b5c6d7e8f90
0x7a3c10|aese v0.16b, v2.16b|v0=a1b2c3d4e5f60718293a4b5c6d7e8f90 v2=1122334455667788
0x7a3c14|aesmc v0.16b, v0.16b|v0=b2c3d4e5f6071829a4b5c6d7e8f90a1b
0x7a3c18|eor v0.16b, v0.16b, v3.16b|v0=b2c3d4e5f6071829a4b5c6d7e8f90a1b v3=99887766554433221100ffeeddccbbaa
0x7a3c1c|ret|x30=0x7a2000
```

- [ ] **Step 2: Write integration test**

```python
# tests/test_integration.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from duckagent.bus import Message, MessageBus
from duckagent.agents.main_agent import MainAgent
from duckagent.agents.trace_agent import TraceAgent


@pytest.fixture
async def system(tmp_path):
    db_path = tmp_path / "test.db"
    bus = MessageBus(db_path=db_path)
    await bus.initialize()

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "main_agent.md").write_text("你是主协调 Agent。")
    (prompts_dir / "trace_agent.md").write_text("你是 Trace 分析 Agent。")

    agent_md = tmp_path / "AGENT.md"
    agent_md.write_text("# Test\n\n逆向测试 APP 签名算法")

    yield {
        "bus": bus,
        "prompts_dir": prompts_dir,
        "agent_md": agent_md,
    }

    await bus.close()


@pytest.mark.asyncio
async def test_full_flow_human_to_trace_and_back(system):
    bus = system["bus"]

    main_response = '{"action": "delegate", "to": "trace_agent", "content": "分析以下 trace 中的加密算法:\\nline 3: aese v0.16b, v1.16b\\nline 4: aesmc v0.16b, v0.16b", "type": "request", "evidence": [], "confidence": "high"}'
    trace_response = "根据 trace 分析，line 3 的 aese 指令和 line 4 的 aesmc 指令表明这是 AES 加密。具体来说是 AES-128，因为只有两轮 aese+aesmc 组合。"
    main_summary = '{"action": "respond", "to": "human", "content": "Trace 分析结果：检测到 AES-128 加密算法，证据在 line 3-4。", "type": "conclusion", "evidence": ["line 3: aese instruction", "line 4: aesmc instruction"], "confidence": "high"}'

    call_count = {"n": 0}
    responses = [main_response, trace_response, main_summary]

    async def mock_completion(*args, **kwargs):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        mock = AsyncMock()
        mock.choices = [AsyncMock(message=AsyncMock(content=responses[idx]))]
        return mock

    with patch("duckagent.agents.base.litellm.acompletion", side_effect=mock_completion):
        main_agent = MainAgent(
            bus=bus,
            model="test-model",
            agent_md_path=system["agent_md"],
            prompts_dir=system["prompts_dir"],
            verify_enabled=False,
        )
        trace_agent = TraceAgent(
            bus=bus,
            model="test-model",
            prompts_dir=system["prompts_dir"],
            verify_enabled=False,
        )

        await main_agent.start()
        await trace_agent.start()

        human_queue = bus.subscribe("human")

        await bus.publish(Message(
            from_agent="human",
            to_agent="main_agent",
            type="request",
            content="分析这段 trace 里的加密算法",
            evidence=[],
            confidence="high",
        ))

        received = await asyncio.wait_for(human_queue.get(), timeout=5.0)
        assert received.to_agent == "human"
        assert "AES" in received.content

        await main_agent.stop()
        await trace_agent.stop()
```

- [ ] **Step 3: Run integration test**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest tests/test_integration.py -v`
Expected: 1 passed

- [ ] **Step 4: Run full test suite**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py data/
git commit -m "feat: integration test verifying full human→main→trace→human flow"
```

---

### Task 13: Final Wiring and Manual Test

**Files:**
- Modify: `src/duckagent/__init__.py`
- Create: `AGENT.md`

- [ ] **Step 1: Create a sample AGENT.md**

```markdown
# AGENT.md

## 项目目标

逆向分析某 Android APP 的请求签名算法。

## 已知信息

- 签名字段在 HTTP header 的 X-Sign 中
- 签名长度 32 字节，疑似 HMAC 或 AES
- 已抓取 trace，包含签名函数的执行流

## Trace 文件

- 汇编: data/sample_trace.txt

## 当前阶段

初步分析，确认加密算法类型。
```

- [ ] **Step 2: Update package __init__.py with version**

```python
# src/duckagent/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Verify duck CLI is installable**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run duck --help`
Expected: shows help with run, log, send commands

- [ ] **Step 4: Verify duck log works**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run duck log`
Expected: "没有消息" or empty (first run, no messages yet)

- [ ] **Step 5: Run full test suite one final time**

Run: `cd /home/duck/NewCode/Projects/Agent/DuckAgent && uv run pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add AGENT.md src/duckagent/__init__.py
git commit -m "feat: sample AGENT.md and final wiring for Phase 1"
```

---

## Summary

| Task | Module | What it delivers |
|------|--------|-----------------|
| 1 | Setup | pyproject.toml, dependencies, package structure |
| 2 | Bus | Message pydantic model |
| 3 | Bus | MessageBus with SQLite + Queue dispatch |
| 4 | Config | Settings via .env + pydantic-settings |
| 5 | Verify | Hard verification (rule-based) |
| 6 | Verify | Model self-check (PASS/FAIL protocol) |
| 7 | Agents | BaseAgent with lifecycle and verification |
| 8 | Agents | System prompts for both agents |
| 9 | Agents | MainAgent with routing logic |
| 10 | Agents | TraceAgent with evidence extraction |
| 11 | CLI | typer app with run/log/send commands |
| 12 | Test | Integration test: full message flow |
| 13 | Final | AGENT.md, CLI verification, final check |
