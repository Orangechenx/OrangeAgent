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
