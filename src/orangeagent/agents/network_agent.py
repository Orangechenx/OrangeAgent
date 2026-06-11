"""Network Agent — 流量分析与接口侦查 Agent。

负责发送 HTTP 请求、分析请求参数、定位签名和加密字段。
"""

from pathlib import Path

import structlog

from orangeagent.bus import Message
from orangeagent.tools import NetworkToolExecutor, NETWORK_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class NetworkAgent(BaseAgent):
    """Agent specialized in network traffic analysis.

    Can send HTTP requests, analyze URL parameters and request bodies,
    identify signature fields, and trace API communication patterns.
    """

    def __init__(
        self,
        bus,
        model: str,
        prompts_dir: Path,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "network_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是网络流量分析 Agent。"

        super().__init__(
            agent_id="network_agent",
            system_prompt=base_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
        )

        self._executor = NetworkToolExecutor()
        self._tools = NETWORK_TOOLS

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
            evidence=["network traffic analysis"],
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
