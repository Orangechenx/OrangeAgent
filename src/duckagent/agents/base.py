import asyncio
import json
from typing import Any

import litellm
import structlog

from duckagent.bus import Message, MessageBus
from duckagent.verify import hard_verify, VerificationError, self_check

logger = structlog.get_logger()


class BaseAgent:
    """Base class for all agents in the system.

    Provides lifecycle management, message dispatch, LLM calling,
    and integrated self-verification for conclusions.
    """

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        bus: MessageBus,
        model: str,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
    ) -> None:
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.bus = bus
        self.model = model
        self.verify_enabled = verify_enabled
        self.verify_max_retries = verify_max_retries
        self.context: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self._queue: asyncio.Queue[Message] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Subscribe to the bus and start the message processing loop."""
        self._queue = self.bus.subscribe(self.agent_id)
        self._task = asyncio.create_task(self._loop())
        logger.info("agent_started", agent_id=self.agent_id)

    async def stop(self) -> None:
        """Cancel the processing loop and unsubscribe from the bus."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.bus.unsubscribe(self.agent_id)
        logger.info("agent_stopped", agent_id=self.agent_id)

    async def _loop(self) -> None:
        """Main message processing loop."""
        assert self._queue is not None
        while True:
            msg = await self._queue.get()
            try:
                await self.on_message(msg)
            except Exception as e:
                logger.error("agent_error", agent_id=self.agent_id, error=str(e))

    async def on_message(self, msg: Message) -> None:
        """Handle an incoming message. Subclasses must override this."""
        raise NotImplementedError

    async def think(self, input_text: str, *, tools: list[dict] | None = None,
                    tool_executor: Any = None, max_iterations: int = 50) -> str:
        """Call the LLM with accumulated context and return the response.

        If tools and tool_executor are provided, enters an agentic loop:
        the model can call tools, results are appended to context, and the
        model is called again until it produces a final text response.
        """
        self.context.append({"role": "user", "content": input_text})

        for _ in range(max_iterations):
            kwargs: dict[str, Any] = {"model": self.model, "messages": self.context}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await litellm.acompletion(**kwargs)
            message = response.choices[0].message

            assistant_entry: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                assistant_entry["tool_calls"] = [
                    tc.model_dump() if hasattr(tc, "model_dump") else tc
                    for tc in tool_calls
                ]
            self.context.append(assistant_entry)

            if not tool_calls:
                return message.content or ""

            if not tool_executor:
                return message.content or ""

            for tc in tool_calls:
                name = tc.function.name
                arguments = json.loads(tc.function.arguments)
                result = tool_executor.execute(name, arguments)
                self.context.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": result,
                })

        return "Reached max iterations without final answer."

    async def send(
        self,
        to: str | None,
        content: str,
        type: str = "conclusion",
        evidence: list[str] | None = None,
        confidence: str = "high",
        reply_to: str | None = None,
    ) -> None:
        """Send a message through the bus, with optional self-verification."""
        msg = Message(
            from_agent=self.agent_id,
            to_agent=to,
            type=type,
            content=content,
            evidence=evidence or [],
            confidence=confidence,
            reply_to=reply_to,
        )

        if self.verify_enabled and msg.type == "conclusion":
            hard_verify(msg)

            for attempt in range(self.verify_max_retries):
                result = await self_check(msg, model=self.model)
                if result.passed:
                    break
                logger.warning(
                    "self_check_failed",
                    agent_id=self.agent_id,
                    attempt=attempt + 1,
                    reason=result.reason,
                )
                if attempt == self.verify_max_retries - 1:
                    await self.bus.publish(Message(
                        from_agent=self.agent_id,
                        to_agent="human",
                        type="question",
                        content=(
                            f"自校验连续失败 {self.verify_max_retries} 次，"
                            f"需要人工审核:\n\n原始结论: {content}\n\n"
                            f"最后一次失败原因: {result.reason}"
                        ),
                        evidence=evidence or [],
                        confidence="low",
                    ))
                    return

                retry_response = await self.think(
                    f"你的上一个结论未通过自校验: {result.reason}\n"
                    f"请重新分析并给出修正后的结论。"
                )
                msg = Message(
                    from_agent=self.agent_id,
                    to_agent=to,
                    type=type,
                    content=retry_response,
                    evidence=evidence or [],
                    confidence=confidence,
                    reply_to=reply_to,
                )
                hard_verify(msg)

        await self.bus.publish(msg)
