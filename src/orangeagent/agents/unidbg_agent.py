"""Unidbg Agent — Native SO 模拟执行与算法复现 Agent。"""

from pathlib import Path
import structlog
from orangeagent.bus import Message
from orangeagent.tools import UnidbgToolExecutor, UNIDBG_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class UnidbgAgent(BaseAgent):
    """Agent specialized in native SO simulation and algorithm recovery via unidbg."""

    def __init__(self, bus, model: str, prompts_dir: Path, verify_enabled: bool = True, verify_max_retries: int = 3) -> None:
        prompt_file = prompts_dir / "unidbg_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 unidbg 模拟执行 Agent。"
        super().__init__(agent_id="unidbg_agent", system_prompt=base_prompt, bus=bus, model=model,
                         verify_enabled=verify_enabled, verify_max_retries=verify_max_retries,
                         skill_tags=["unidbg", "native"],
                         allowed_toolsets={"unidbg"})
        self._executor = UnidbgToolExecutor()
        self._tools = UNIDBG_TOOLS

    async def stop(self) -> None:
        self._executor.close()
        await super().stop()

    async def on_message(self, msg: Message) -> None:
        if msg.type not in ("request", "question"):
            return
        addressed_to_us = msg.to_agent == self.agent_id or (msg.mentions and self.agent_id in msg.mentions)
        if not addressed_to_us:
            return
        input_text = f"[来自 {msg.from_agent}]: {msg.content}" if msg.from_agent else msg.content
        response = await self.think(input_text, tools=self._tools, tool_executor=self._executor,
                                     session_id=msg.session_id, task_id=msg.task_id, run_id=msg.run_id)
        reply_to = msg.from_agent if msg.from_agent != "human" else "human"
        await self.send(to=reply_to, content=response, type="conclusion", evidence=["unidbg simulation"],
                         confidence="high", reply_to=msg.id, session_id=msg.session_id,
                         task_id=msg.task_id, run_id=msg.run_id)
