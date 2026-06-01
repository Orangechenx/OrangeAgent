import re
from pathlib import Path

import structlog

from duckagent.bus import Message
from duckagent.tools import LocalTraceToolExecutor, TRACE_TOOLS
from .base import BaseAgent

logger = structlog.get_logger()


class TraceAgent(BaseAgent):
    """Agent specialized in analyzing ARM64 execution traces.

    When trace files are provided, uses tool calling (trace_search, trace_context,
    trace_cross_ref) to navigate large trace files autonomously.
    """

    def __init__(
        self,
        bus,
        model: str,
        prompts_dir: Path,
        trace_files: dict[str, Path] | None = None,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        prompt_file = prompts_dir / "trace_agent.md"
        base_prompt = prompt_file.read_text() if prompt_file.exists() else "你是 Trace 分析 Agent。"

        super().__init__(
            agent_id="trace_agent",
            system_prompt=base_prompt,
            bus=bus,
            model=model,
            verify_enabled=verify_enabled,
            verify_max_retries=verify_max_retries,
        )

        self._executor: LocalTraceToolExecutor | None = None
        self._tools: list[dict] | None = None
        if trace_files:
            existing = {k: v for k, v in trace_files.items() if v.exists()}
            if existing:
                self._executor = LocalTraceToolExecutor(existing)
                self._tools = TRACE_TOOLS

    async def stop(self) -> None:
        if self._executor:
            self._executor.close()
        await super().stop()

    async def on_message(self, msg: Message) -> None:
        """Handle incoming messages. Only processes type='request'."""
        if msg.type != "request":
            return

        response = await self.think(
            msg.content,
            tools=self._tools,
            tool_executor=self._executor,
        )

        evidence = self._extract_evidence(response)

        await self.send(
            to=msg.from_agent,
            content=response,
            type="conclusion",
            evidence=evidence if evidence else ["analysis based on provided trace"],
            confidence=self._assess_confidence(response),
            reply_to=msg.id,
        )

    @staticmethod
    def _extract_evidence(text: str) -> list[str]:
        """Extract line number references from the analysis text."""
        pattern = r"line \d+[^.;\n]*"
        matches = re.findall(pattern, text, re.IGNORECASE)
        return matches

    @staticmethod
    def _assess_confidence(text: str) -> str:
        """Assess confidence level based on hedging language in the response."""
        low_indicators = ["不确定", "可能", "疑似", "unclear", "might", "possibly"]
        for indicator in low_indicators:
            if indicator in text.lower():
                return "low"
        return "high"
