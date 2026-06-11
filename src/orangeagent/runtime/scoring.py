import re

from .models import MemoryRecord

_SOURCE_WEIGHT = {
    "user": 1.00,
    "tool": 0.95,
    "trace": 0.95,
    "jadx": 0.90,
    "agent": 0.55,
    "llm": 0.10,
}

_STATUS_WEIGHT = {
    "pinned": 1.00,
    "active": 0.90,
    "verified": 0.85,
    "tentative": 0.35,
    "archived": 0.20,
    "superseded": -0.20,
    "rejected": -0.80,
}

_SCOPE_WEIGHT = {
    "working": 0.50,
    "task": 0.40,
    "project": 0.25,
    "long_term": 0.10,
}

_CONFIDENCE_WEIGHT = {
    "high": 0.35,
    "medium": 0.20,
    "low": 0.05,
}


def score_memory(
    memory: MemoryRecord,
    *,
    query: str = "",
    task_id: str | None = None,
) -> float:
    """计算记忆注入权重。

    rejected/superseded 记忆保留用于提醒，但不会作为正向依据排序靠前。
    """
    score = 0.0
    score += _SOURCE_WEIGHT.get(memory.source, 0.10)
    score += _STATUS_WEIGHT.get(memory.status, 0.0)
    score += _SCOPE_WEIGHT.get(memory.scope, 0.0)
    score += _CONFIDENCE_WEIGHT.get(memory.confidence, 0.0)

    if memory.evidence_refs:
        score += min(len(memory.evidence_refs), 3) * 0.12

    if task_id and memory.task_id == task_id:
        score += 0.30

    score += _keyword_overlap(query, memory.content) * 0.08

    if memory.status == "rejected":
        score -= 1.0
    if memory.status == "superseded":
        score -= 0.5

    return round(score, 4)


def _keyword_overlap(query: str, content: str) -> int:
    if not query:
        return 0
    query_words = _tokens(query)
    if not query_words:
        return 0
    content_words = _tokens(content)
    return len(query_words & content_words)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_.$'-]+|[\u4e00-\u9fff]{2,}", text)
        if len(token.strip()) >= 2
    }
