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


# --- MessageBus tests ---

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
