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
