from dataclasses import dataclass

import litellm

from orangeagent.bus.models import Message

_SELF_CHECK_PROMPT = """审视以下结论和证据，判断推理链是否有逻辑漏洞或证据不足。

结论: {content}

证据:
{evidence}

置信度: {confidence}

如果推理链合理且证据充分，回复 "PASS: <简短理由>"。
如果有问题，回复 "FAIL: <具体问题>"。"""


@dataclass
class CheckResult:
    passed: bool
    reason: str


async def self_check(msg: Message, model: str) -> CheckResult:
    """Send conclusion + evidence back to LLM for self-review.

    Non-conclusion messages are auto-passed without calling the model.
    """
    if msg.type != "conclusion":
        return CheckResult(passed=True, reason="non-conclusion, skipped")

    prompt = _SELF_CHECK_PROMPT.format(
        content=msg.content,
        evidence="\n".join(f"- {e}" for e in msg.evidence),
        confidence=msg.confidence,
    )

    response = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    reply = response.choices[0].message.content.strip()

    # 判定策略：只有明确 FAIL 才拦截，其余放行。
    # 旧实现只认 "PASS" 前缀，会把 "OK:..."/"CORRECT:..." 等正面回复误判为失败、
    # 触发不必要的重试，重试耗尽后还可能拒发正确结论。
    upper = reply.upper()
    if upper.startswith("PASS"):
        return CheckResult(passed=True, reason=reply)
    if upper.startswith("FAIL"):
        return CheckResult(passed=False, reason=reply)
    # 非标准格式：扫描明确的否定信号，命中才判失败
    fail_markers = ("逻辑漏洞", "证据不足", "不充分", "矛盾", "无法支持", "存在问题")
    if any(m in reply for m in fail_markers):
        return CheckResult(passed=False, reason=reply)
    return CheckResult(passed=True, reason=reply)
