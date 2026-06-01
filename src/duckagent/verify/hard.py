from duckagent.bus.models import Message


class VerificationError(Exception):
    pass


def hard_verify(msg: Message) -> None:
    """Rule-based verification for conclusion messages.

    Checks structural requirements before a conclusion is published.
    Non-conclusion messages are passed through without checks.
    """
    if msg.type != "conclusion":
        return

    if not msg.evidence:
        raise VerificationError(
            f"Conclusion from {msg.from_agent} has empty evidence. "
            f"Content: {msg.content[:100]}"
        )
