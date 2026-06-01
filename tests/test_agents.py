import asyncio
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
            from_agent="human",
            to_agent="echo_agent",
            type="request",
            content="first",
            evidence=[],
            confidence="high",
        ))
        await asyncio.sleep(0.2)

        # system + user msg + assistant response
        assert len(agent.context) == 3

        await agent.stop()


# --- MainAgent tests ---

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
