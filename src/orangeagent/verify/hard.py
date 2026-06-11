import re

from orangeagent.bus.models import Message


class VerificationError(Exception):
    pass


_TRACE_LINE_RE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_JADX_REF_RE = re.compile(r"\b[\w.$]+\.[\w$<>]+\b")


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

    evidence_text = "\n".join(msg.evidence)
    if msg.confidence in {"high", "medium"} and msg.from_agent == "trace_agent":
        if not _TRACE_LINE_RE.search(evidence_text):
            raise VerificationError(
                "trace_agent 的中高置信结论必须包含可定位的 trace 行号证据"
            )

    if msg.confidence in {"high", "medium"} and msg.from_agent == "ida_jadx_agent":
        if not _JADX_REF_RE.search(evidence_text):
            raise VerificationError(
                "ida_jadx_agent 的中高置信结论必须包含类名或方法引用证据"
            )
