"""Frida Agent — 动态分析 Agent。

负责运行时 Hook、类枚举、方法调用追踪。
"""

from pathlib import Path

import structlog

from orangeagent.bus import Message
from orangeagent.tools import FridaToolExecutor, FRIDA_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class FridaAgent(BaseAgent):
    """Agent specialized in dynamic analysis using Frida.

    Can hook Java methods, enumerate loaded classes, list processes,
    and generate Frida scripts for offline use.
    """

    def __init__(
        self,
        bus,
        model: str,
        prompts_dir: Path,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "frida_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 Frida 动态分析 Agent。"

        super().__init__(
            agent_id="frida_agent",
            system_prompt=base_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
            skill_tags=["hook", "frida", "dynamic", "ssl"],
        )

        self._executor = FridaToolExecutor()
        self._tools = FRIDA_TOOLS

    async def stop(self) -> None:
        if self._executor:
            self._executor.close()
        await super().stop()

    async def on_message(self, msg: Message) -> None:
        if msg.type not in ("request", "question"):
            return
        addressed_to_us = (
            msg.to_agent == self.agent_id or
            (msg.mentions and self.agent_id in msg.mentions)
        )
        if not addressed_to_us:
            return

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

        reply_to = msg.from_agent if msg.from_agent != "human" else "human"

        await self.send(
            to=reply_to,
            content=response,
            type="conclusion",
            evidence=["frida dynamic analysis"],
            confidence=self._assess_confidence(response),
            reply_to=msg.id,
            session_id=msg.session_id,
            task_id=msg.task_id,
            run_id=msg.run_id,
        )

    @staticmethod
    def _assess_confidence(text: str) -> str:
        low_indicators = ["不确定", "可能", "疑似", "unclear", "might", "possibly"]
        for indicator in low_indicators:
            if indicator in text.lower():
                return "low"
        return "high"
