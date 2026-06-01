import json
import re
from pathlib import Path

import structlog

from duckagent.bus import Message
from .base import BaseAgent

logger = structlog.get_logger()

_ROUTING_INSTRUCTION = """

## 回复格式

你必须以纯 JSON 格式回复（不要用 markdown code block 包裹），包含以下字段：
{"action": "respond|delegate", "to": "目标agent或human", "content": "消息内容", "type": "conclusion|request|question", "evidence": [...], "confidence": "high|medium|low"}

- action=respond: 直接回复
- action=delegate: 转发给其他 agent（拆解成具体问题）

重要：直接输出 JSON，不要加 ```json 标记。
"""


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
        """Handle incoming message: think, parse JSON response, and route."""
        response = await self.think(
            f"[来自 {msg.from_agent}] (type={msg.type}): {msg.content}"
        )

        parsed = self._parse_json_response(response)
        if parsed is None:
            logger.warning(
                "main_agent_non_json_response",
                response_preview=response[:100],
            )
            await self.send(
                to=msg.from_agent if msg.from_agent != "human" else "human",
                content=response,
                type="conclusion",
                evidence=["model response"],
                confidence="medium",
                reply_to=msg.id,
            )
            return

        await self.send(
            to=parsed.get("to"),
            content=parsed.get("content", response),
            type=parsed.get("type", "conclusion"),
            evidence=parsed.get("evidence", []),
            confidence=parsed.get("confidence", "medium"),
            reply_to=msg.id,
        )

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        """Try to parse JSON from response, handling markdown code blocks."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        return None
