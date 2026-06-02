"""Pure-function dispatch logic for message routing.

Extracted from LocalMessageBus._dispatch() so it can be shared
by both the in-process bus and the FastAPI server.
"""

from duckagent.bus.models import Message


def resolve_recipients(msg: Message, active_agent_ids: set[str]) -> set[str]:
    """Determine which agents should receive a message.

    Rules (matching LocalMessageBus._dispatch):
    1. to_agent + mentions are the explicit recipients (union)
    2. If no explicit recipients, broadcast to all active agents
    3. Sender never receives their own message

    Returns a set of agent_id strings.
    """
    recipients: set[str] = set()

    # 1. Explicit recipients: to_agent + mentions
    if msg.to_agent:
        recipients.add(msg.to_agent)
    for agent_id in msg.mentions:
        recipients.add(agent_id)

    # 2. Fallback: broadcast
    if not recipients:
        recipients = active_agent_ids.copy()

    # 3. Never send to self
    recipients.discard(msg.from_agent)

    return recipients


def should_persist(msg: Message) -> bool:
    """Status messages are never persisted to SQLite."""
    return msg.type != "status"
