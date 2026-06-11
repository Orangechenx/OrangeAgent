import pytest
from orangeagent.bus.models import Message
from orangeagent.verify.hard import hard_verify, VerificationError


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


def test_hard_verify_requires_trace_line_for_trace_agent_high_confidence():
    msg = Message(
        from_agent="trace_agent",
        to_agent="human",
        type="conclusion",
        content="这是 HMAC-SHA256",
        evidence=["analysis based on provided trace"],
        confidence="high",
    )

    with pytest.raises(VerificationError, match="trace 行号"):
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


# --- Self-check tests ---

from unittest.mock import AsyncMock, patch
from orangeagent.verify.self_check import self_check, CheckResult


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
    with patch("orangeagent.verify.self_check.litellm.acompletion") as mock:
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
    with patch("orangeagent.verify.self_check.litellm.acompletion") as mock:
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
