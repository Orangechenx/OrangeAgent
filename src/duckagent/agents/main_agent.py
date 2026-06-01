import re
from pathlib import Path

import structlog

from duckagent.bus import Message
from .base import BaseAgent

logger = structlog.get_logger()

_ROUTING_INSTRUCTION = """

## 回复格式

请用自然语言回复，使用 markdown 格式组织内容。

**委托规则：** 只有当用户明确要求分析 trace/sign/签名/加密/Native 时才委托。
对话性的消息（打招呼、闲聊、询问状态）直接回复，不要委托。

委托时在第一行加上：
>>> DELEGATE TO trace_agent

下面写要委托的具体分析任务。
"""


_CASUAL_KEYWORDS = {"你好", "hello", "hi", "hey", "在吗", "在?", "谢谢", "thanks", "ok", "好的", "嗯", "哦"}

_ANALYSIS_KEYWORDS = {"trace", "sign", "签名", "加密", "AES", "HMAC", "密钥", "key",
                       "分析", "analyze", "check", "检查", "帮我", "定位", "查找",
                       "native", "so", "elf", "arm", "反编译", "逆向"}


class MainAgent(BaseAgent):
    """Main coordinating agent that routes messages and loads project context."""

    def __init__(
        self,
        bus,
        model: str,
        agent_md_path: Path,
        prompts_dir: Path,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "main_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是主协调 Agent。"

        agent_md_content = ""
        if agent_md_path.exists():
            agent_md_content = agent_md_path.read_text()

        system_prompt = f"{base_prompt}\n\n## 项目上下文\n\n{agent_md_content}{_ROUTING_INSTRUCTION}"

        super().__init__(
            agent_id="main_agent",
            system_prompt=system_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
        )

    async def on_message(self, msg: Message) -> None:
        """Handle incoming message: think, route by delegation marker."""
        # Short-circuit casual conversation — no LLM call, no delegation
        if self._is_casual(msg.content):
            await self.send(
                to="human",
                content=self._casual_reply(),
                type="conclusion",
                evidence=["casual shortcut"],
                confidence="high",
                reply_to=msg.id,
            )
            return

        response = await self.think(
            f"[来自 {msg.from_agent}] (type={msg.type}): {msg.content}"
        )

        # Check for delegation marker
        delegate_match = re.match(r">>>\s*DELEGATE\s+TO\s+(\w+)", response)
        if delegate_match:
            target = delegate_match.group(1)
            # Remove the marker line from the delegated content
            task_content = response[delegate_match.end():].strip()
            if not task_content:
                task_content = msg.content
            await self.send(
                to=target,
                content=task_content,
                type="request",
                evidence=[msg.id] if msg.id else [],
                confidence="high",
                reply_to=msg.id,
            )
            return

        # No delegation — always respond to human
        content = self._strip_json_artifacts(response)
        await self.send(
            to="human",
            content=content,
            type="conclusion",
            evidence=["model response"],
            confidence="medium",
            reply_to=msg.id,
        )

    @staticmethod
    def _is_casual(text: str) -> bool:
        """Check if a message is casual conversation (no analysis intent)."""
        text_lower = text.strip().lower()
        # Too short to be a real analysis request
        if len(text_lower) <= 3:
            return True
        # Contains casual keywords and no analysis keywords
        has_casual = any(kw in text_lower for kw in _CASUAL_KEYWORDS)
        has_analysis = any(kw in text_lower for kw in _ANALYSIS_KEYWORDS)
        return has_casual and not has_analysis

    @staticmethod
    def _casual_reply() -> str:
        return "你好！有什么逆向分析任务需要我帮忙？"

    @staticmethod
    def _strip_json_artifacts(text: str) -> str:
        """Remove JSON code blocks or raw JSON objects from display text."""
        # Remove ```json ... ``` blocks entirely
        text = re.sub(r"```(?:json)?\s*\n?\{[^`]*\}\n?\s*```", "", text, flags=re.DOTALL)
        # If the ENTIRE response is a JSON object, replace with a clean message
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            # Try to extract "content" field as last resort
            m = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', stripped)
            if m:
                try:
                    return m.group(1).encode().decode("unicode_escape")
                except Exception:
                    pass
            return "收到回复，但格式异常，请重新提问。"
        return stripped
