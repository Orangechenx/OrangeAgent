"""IDA Agent — Native 静态深度分析 Agent。"""

from pathlib import Path
import structlog
from orangeagent.bus import Message
from orangeagent.tools import IdaToolExecutor, IDA_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class IdaAgent(BaseAgent):
    """Agent specialized in native binary analysis via IDA Pro."""

    def __init__(self, bus, model: str, prompts_dir: Path, verify_enabled: bool = True, verify_max_retries: int = 3) -> None:
        prompt_file = prompts_dir / "ida_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 IDA Pro 静态分析 Agent。"
        super().__init__(agent_id="ida_agent", system_prompt=base_prompt, bus=bus, model=model,
                         verify_enabled=verify_enabled, verify_max_retries=verify_max_retries)
        self._executor = IdaToolExecutor()
        self._tools = IDA_TOOLS

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
        await self.send(to=reply_to, content=response, type="conclusion", evidence=["ida analysis"],
                         confidence="high", reply_to=msg.id, session_id=msg.session_id,
                         task_id=msg.task_id, run_id=msg.run_id)
