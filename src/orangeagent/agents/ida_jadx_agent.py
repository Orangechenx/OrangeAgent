import re
from pathlib import Path

import structlog

from orangeagent.bus import Message
from orangeagent.tools import JadxToolExecutor, JADX_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class IdaJadxAgent(BaseAgent):
    """Agent specialized in static analysis of decompiled APK code via JADX.

    Uses JADX tools to search classes, read source code, find cross-references,
    and analyze Android manifest/resources.
    """

    def __init__(
        self,
        bus,
        model: str,
        prompts_dir: Path,
        jadx_host: str = "127.0.0.1",
        jadx_port: int = 8650,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "ida_jadx_agent.md"
        base_prompt = (
            prompt_file.read_text()
            if prompt_file.exists()
            else "你是 JADX 静态分析 Agent。"
        )

        super().__init__(
            agent_id="ida_jadx_agent",
            system_prompt=base_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
            skill_tags=["jadx", "ida", "static", "decompile"],
        )

        self._executor = JadxToolExecutor(
            jadx_host=jadx_host,
            jadx_port=jadx_port,
        )
        self._tools = JADX_TOOLS

    async def stop(self) -> None:
        if self._executor:
            self._executor.close()
        await super().stop()

    async def on_message(self, msg: Message) -> None:
        """Handle incoming messages.

        Only processes actionable message types (request, question).
        Being @mentioned in a conclusion/decision is just informational (CC) — no action.
        """
        # Only request and question require action
        if msg.type not in ("request", "question"):
            return
        # Must be addressed to us: either direct target or @mentioned
        addressed_to_us = (
            msg.to_agent == self.agent_id or
            (msg.mentions and self.agent_id in msg.mentions)
        )
        if not addressed_to_us:
            return

        # Build context-aware input
        input_text = msg.content
        if msg.from_agent:
            input_text = f"[来自 {msg.from_agent}]: {input_text}"

        response = await self.think(
            input_text,
            tools=self._tools,
            tool_executor=self._executor,
            session_id=msg.session_id,
            task_id=msg.task_id,
            run_id=msg.run_id,
        )

        evidence = self._extract_evidence(response)

        # Respond to sender (or human if it was from human)
        reply_to = msg.from_agent if msg.from_agent != "human" else "human"

        await self.send(
            to=reply_to,
            content=response,
            type="conclusion",
            evidence=evidence if evidence else ["analysis based on APK static analysis"],
            confidence=self._assess_confidence(response),
            reply_to=msg.id,
            session_id=msg.session_id,
            task_id=msg.task_id,
            run_id=msg.run_id,
        )

    @staticmethod
    def _extract_evidence(text: str) -> list[str]:
        """Extract class name and method references as evidence."""
        patterns = [
            r'(?:class|类)\s+([\w.$]+)',
            r'(?:method|方法)\s+([\w.$<>()]+)',
        ]
        evidence: list[str] = []
        for pattern in patterns:
            evidence.extend(re.findall(pattern, text, re.IGNORECASE))
        return evidence[:10]  # limit

    @staticmethod
    def _assess_confidence(text: str) -> str:
        """Assess confidence level based on hedging language in the response."""
        low_indicators = ["不确定", "可能", "疑似", "unclear", "might", "possibly"]
        for indicator in low_indicators:
            if indicator in text.lower():
                return "low"
        return "high"
