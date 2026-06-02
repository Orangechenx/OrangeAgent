"""Tests for the dispatcher — pure-function message routing logic."""

import pytest
from duckagent.bus.models import Message
from duckagent.server.dispatcher import resolve_recipients, should_persist


def make_msg(from_agent="main_agent", to_agent=None, mentions=None, type="request"):
    return Message(
        from_agent=from_agent,
        to_agent=to_agent,
        mentions=mentions or [],
        type=type,
        content="test",
        evidence=[],
        confidence="high",
    )


def test_to_agent_only():
    recipients = resolve_recipients(
        make_msg(to_agent="trace_agent"),
        {"main_agent", "trace_agent", "ida_jadx_agent"},
    )
    assert recipients == {"trace_agent"}


def test_mentions_only():
    recipients = resolve_recipients(
        make_msg(mentions=["trace_agent", "ida_jadx_agent"]),
        {"main_agent", "trace_agent", "ida_jadx_agent"},
    )
    assert recipients == {"trace_agent", "ida_jadx_agent"}


def test_to_agent_and_mentions_union():
    recipients = resolve_recipients(
        make_msg(to_agent="trace_agent", mentions=["ida_jadx_agent"]),
        {"main_agent", "trace_agent", "ida_jadx_agent"},
    )
    assert recipients == {"trace_agent", "ida_jadx_agent"}


def test_broadcast_when_no_explicit_recipients():
    recipients = resolve_recipients(
        make_msg(to_agent=None, mentions=[]),
        {"main_agent", "trace_agent", "ida_jadx_agent"},
    )
    # Sender excluded, others get it
    assert recipients == {"trace_agent", "ida_jadx_agent"}


def test_sender_excluded():
    recipients = resolve_recipients(
        make_msg(from_agent="trace_agent"),
        {"main_agent", "trace_agent", "ida_jadx_agent"},
    )
    assert "trace_agent" not in recipients
    assert recipients == {"main_agent", "ida_jadx_agent"}


def test_sender_excluded_from_explicit_to():
    """Even if sender sets to_agent to themselves, they don't get it."""
    recipients = resolve_recipients(
        make_msg(from_agent="trace_agent", to_agent="trace_agent"),
        {"main_agent", "trace_agent"},
    )
    assert recipients == set()


def test_sender_excluded_from_mentions():
    recipients = resolve_recipients(
        make_msg(from_agent="trace_agent", mentions=["trace_agent", "main_agent"]),
        {"main_agent", "trace_agent"},
    )
    assert recipients == {"main_agent"}


def test_unknown_agent_returned_as_is():
    """resolve_recipients returns agent IDs even if not connected.

    Filtering by connected status is the ConnectionManager's job,
    not the dispatcher's. The dispatcher just resolves routing.
    """
    recipients = resolve_recipients(
        make_msg(to_agent="unknown_agent"),
        {"main_agent", "trace_agent"},
    )
    # unknown_agent is in the result — ConnectionManager will safely ignore it
    assert recipients == {"unknown_agent"}


def test_should_persist_normal():
    assert should_persist(make_msg(type="request")) is True
    assert should_persist(make_msg(type="conclusion")) is True
    assert should_persist(make_msg(type="question")) is True
    assert should_persist(make_msg(type="decision")) is True


def test_should_persist_status():
    assert should_persist(make_msg(type="status")) is False
