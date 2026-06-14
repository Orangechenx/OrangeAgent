"""JS Reverse Agent — WebView/JS 反混淆 Agent。"""

from pathlib import Path
import structlog
from orangeagent.bus import Message
from orangeagent.tools import JsReverseExecutor, JS_REVERSE_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class JsReverseAgent(BaseAgent):
    """Agent specialized in JavaScript deobfuscation and WebView analysis."""

    def __init__(self, bus, model: str, prompts_dir: Path, verify_enabled: bool = True, verify_max_retries: int = 3) -> None:
        prompt_file = prompts_dir / "js_reverse_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 JavaScript 逆向分析 Agent。"
        super().__init__(agent_id="js_reverse_agent", system_prompt=base_prompt, bus=bus, model=model,
                         verify_enabled=verify_enabled, verify_max_retries=verify_max_retries,
                         skill_tags=["javascript", "deobfuscate"],
                         allowed_toolsets={"js_reverse"})
        self._executor = JsReverseExecutor()
        self._tools = JS_REVERSE_TOOLS

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
        await self.send(to=reply_to, content=response, type="conclusion", evidence=["js analysis"],
                         confidence="high", reply_to=msg.id, session_id=msg.session_id,
                         task_id=msg.task_id, run_id=msg.run_id)
