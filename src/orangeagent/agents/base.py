import asyncio
import json
import math
import re
import time
from typing import Any
from uuid import uuid4

import litellm
import structlog

from orangeagent.bus import Message, MessageBus
from orangeagent.runtime.event import (
    Event, EventKind, Sink, DISCARD,
    agent_status_event, llm_call_event, tool_call_event, cache_info_event,
)
from orangeagent.runtime.guardrails import check_tool_policy
from orangeagent.runtime.middleware import (
    MiddlewarePipeline, MiddlewareResult, audit_middleware,
    storm_breaker_middleware,
)
from orangeagent.runtime.models import RunStepRecord, ToolCallRecord
from orangeagent.runtime.skill_store import SkillStore
from orangeagent.tools.registry import get
from orangeagent.tools.skill_loader import set_skill_store as _init_skill_store
from orangeagent.runtime.sop import build_reverse_sop_context
from orangeagent.verify import hard_verify, VerificationError, self_check

logger = structlog.get_logger()

_AT_MENTION_RE = re.compile(r"(?<!\w)@(\w[\w_-]*\w)")

# ── Loop 优化常量（参考 Reasonix） ──
_MAX_EMPTY_FINAL_BLOCKS = 3       # 空回答最多重试 3 次
_MAX_READINESS_BLOCKS = 3         # 工具就绪检查最多 nudge 3 次
_MAX_CONTEXT_TOOL_ROUNDS = 20     # 上下文保留最近 20 轮 tool call
_COMPACT_INTERVAL = 15            # 每 15 条消息压缩一次

# ── 工具输出截断（参考 Reasonix） ──
_MAX_TOOL_OUTPUT_BYTES = 32 * 1024  # 32KB 单次工具结果上限


def _truncate_tool_output(result: str) -> str:
    """截断工具输出，保留头尾 + 省略标记。

    参考 Reasonix 的 truncateToolOutput：超出 32KB 时保留头尾各一半。
    """
    raw_bytes = result.encode("utf-8")
    if len(raw_bytes) <= _MAX_TOOL_OUTPUT_BYTES:
        return result
    keep = _MAX_TOOL_OUTPUT_BYTES // 2
    head = raw_bytes[:keep].decode("utf-8", errors="replace")
    tail = raw_bytes[-keep:].decode("utf-8", errors="replace")
    omitted = len(raw_bytes) - keep * 2
    notice = (
        f"\n\n…[工具输出截断: 省略 {omitted} 字节 / "
        f"{math.ceil(omitted / 4)} token — "
        f"缩小查询范围后重试]…\n\n"
    )
    return head + notice + tail


class BaseAgent:
    """Base class for all agents in the system.

    Provides lifecycle management, message dispatch, LLM calling,
    and integrated self-verification for conclusions.

    Optimizations (Reasonix/codex-ds inspired):
    - Memory 合成进 system prompt（prompt caching 友好）
    - 空回答自动恢复（最多 3 次）
    - 工具就绪检查（跳过工具时 nudge）
    - 上下文自动压缩（保留最近 N 轮工具调用）
    - 工具输出截断（32KB 上限）
    - 事件系统（Sink 解耦 UI）
    - 缓存命中诊断（cache diagnostics）
    """

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        bus: MessageBus,
        model: str,
        verify_enabled: bool = True,
        verify_max_retries: int = 3,
        sink: Sink | None = None,
        middleware: MiddlewarePipeline | None = None,
        skill_store: SkillStore | None = None,
        skill_tags: list[str] | None = None,
        enable_default_middleware: bool = True,
        allowed_toolsets: set[str] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self._raw_system_prompt = system_prompt
        self.bus = bus
        self.model = model
        self.verify_enabled = verify_enabled
        self.verify_max_retries = verify_max_retries
        self._queue: asyncio.Queue[Message] | None = None
        self._task: asyncio.Task | None = None
        # 事件系统
        self._sink = sink or DISCARD
        # 允许的工具集（None = 全部放行）
        self._allowed_toolsets = allowed_toolsets
        # 中间件管道
        self._middleware = middleware or MiddlewarePipeline(sink=self._sink)
        if enable_default_middleware:
            self._middleware.use(audit_middleware(sink=self._sink))
            self._middleware.use(storm_breaker_middleware())
        # 技能系统
        self._skill_store = skill_store
        self._skill_tags = skill_tags or []
        if skill_store is not None:
            _init_skill_store(skill_store)
        # 记忆注入缓存
        self._composed_prompt: str | None = None
        self._memory_block: str | None = None
        self._memory_version: int = 0
        self._last_compact_len: int = 0
        # 缓存诊断（参考 Reasonix：sessCacheHit/sessCacheMiss）
        self._cache_hit: int = 0
        self._cache_miss: int = 0

    @property
    def cache_hit_ratio(self) -> float:
        """缓存命中率。"""
        total = self._cache_hit + self._cache_miss
        return self._cache_hit / total if total > 0 else 0.0

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
            if msg.type == "status":
                continue
            try:
                await self.on_message(msg)
            except Exception as e:
                logger.error(
                    "agent_error",
                    message="Agent 处理消息失败",
                    agent_id=self.agent_id,
                    error=str(e),
                )
                await self._broadcast_status("idle", task_summary=f"错误: {e}")
                await self.bus.publish(Message(
                    from_agent=self.agent_id,
                    to_agent="human",
                    type="conclusion",
                    content=f"处理消息时出错: {e}",
                    evidence=[str(msg.id)],
                    confidence="low",
                    reply_to=msg.id,
                ))

    @staticmethod
    def _parse_mentions(text: str) -> list[str]:
        """Extract unique @agent_id mentions in order of first appearance."""
        return list(dict.fromkeys(_AT_MENTION_RE.findall(text)))

    async def on_message(self, msg: Message) -> None:
        """Handle an incoming message.

        Default behavior: if mentions is non-empty and this agent is not
        mentioned, skip processing. If mentions is empty (broadcast), process.
        Subclasses should override for specific behavior but may call
        super().on_message(msg) as a guard.
        """
        if msg.mentions and self.agent_id not in msg.mentions:
            return
        raise NotImplementedError

    async def _broadcast_status(self, state: str, task_summary: str = "") -> None:
        content = json.dumps({"state": state, "task_summary": task_summary}, ensure_ascii=False)
        msg = Message(
            from_agent=self.agent_id,
            to_agent=None,
            type="status",
            content=content,
            evidence=[],
            confidence="high",
        )
        await self.bus.publish(msg)
        self._sink.emit(agent_status_event(
            agent_id=self.agent_id,
            state=state,
            task_summary=task_summary,
        ))

    # ─── System Prompt 合成（记忆注入优化） ─────────────────────────

    @property
    def system_prompt(self) -> str:
        """向后兼容：返回原始 system prompt。"""
        return self._raw_system_prompt

    @property
    def effective_system_prompt(self) -> str:
        """合成后的 system prompt：base + SOP + 记忆上下文（缓存）。

        记忆块合成进 system prompt 而非 user message，利用 prompt caching。
        """
        if self._composed_prompt is not None:
            return self._composed_prompt
        self._composed_prompt = self._build_composed_prompt()
        return self._composed_prompt

    def _build_composed_prompt(self) -> str:
        """构建包含 SOP + 持久记忆 + 匹配技能的 system prompt。"""
        parts = [self._raw_system_prompt]

        sop = build_reverse_sop_context(self.agent_id)
        if sop:
            parts.append(sop)

        if self._memory_block:
            parts.append(self._memory_block)

        # 自动注入匹配的技能
        skills_block = self._build_skills_block()
        if skills_block:
            parts.append(skills_block)

        return "\n\n".join(parts)

    def _build_skills_block(self) -> str:
        """构建技能目录，注入 system prompt。

        如果 skill_tags 为空，返回所有技能（适用于 main_agent）。
        如果 skill_tags 有值，只返回匹配的技能。
        """
        if not self._skill_store:
            return ""
        # 使用 catalog_instruction 生成格式化目录
        return self._skill_store.catalog_instruction(budget=4000)

    def invalidate_composed_prompt(self) -> None:
        """记忆变更时失效缓存，下次 think() 重建。"""
        self._composed_prompt = None

    async def _refresh_memory_block(self) -> None:
        """从 store 刷新跨 session 的高权重记忆块，注入 system prompt。"""
        build_system_context = getattr(self.bus, "build_system_context", None)
        if build_system_context is None:
            return
        try:
            block = await build_system_context(limit=15)
            if block and block != self._memory_block:
                self._memory_block = block
                self._memory_version += 1
                self.invalidate_composed_prompt()
        except Exception as exc:
            logger.warning(
                "memory_refresh_failed",
                agent_id=self.agent_id,
                error=str(exc)[:120],
            )

    async def think(
        self,
        input_text: str,
        *,
        tools: list[dict] | None = None,
        tool_executor: Any = None,
        max_iterations: int = 50,
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        """优化的思考循环（参考 Reasonix 设计）。

        改进点：
        1. 记忆合成进 system prompt（prompt caching 友好）
        2. 空回答自动恢复（最多 3 次）
        3. 工具就绪检查（跳过工具时 nudge）
        4. 上下文迭代间自动压缩
        """
        # ── 1. 刷新记忆块，合成 system prompt ──
        await self._refresh_memory_block()

        context: list[dict[str, Any]] = [
            {"role": "system", "content": self.effective_system_prompt},
            {"role": "user", "content": input_text},
        ]
        await self._broadcast_status("thinking", task_summary=input_text[:80])
        if session_id and run_id:
            await self._record_run_step(
                session_id=session_id, task_id=task_id, run_id=run_id,
                step_type="checkpoint", title="开始推理",
                content=f"tools={bool(tools)}",
                metadata={"agent_id": self.agent_id}, status="ok",
            )

        # ── 2. 循环状态 ──
        empty_final_blocks = 0
        readiness_blocks = 0
        used_any_tool = False

        for _ in range(max_iterations):
            # ── 2a. 调用 LLM ──
            kwargs: dict[str, Any] = {"model": self.model, "messages": context}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            started = time.monotonic()
            response = await self._call_llm_with_retry(**kwargs)
            duration_ms = int((time.monotonic() - started) * 1000)

            # ── 缓存诊断（参考 Reasonix cache diagnostics） ──
            usage = getattr(response, "usage", None)
            if usage:
                try:
                    total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
                    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    cached_tokens = int(getattr(usage, "cached_prompt_tokens", 0) or 0)
                except (TypeError, ValueError):
                    total_tokens = prompt_tokens = cached_tokens = 0
                if cached_tokens > 0:
                    self._cache_hit += cached_tokens
                self._cache_miss += max(0, prompt_tokens - cached_tokens)
                self._sink.emit(cache_info_event(
                    agent_id=self.agent_id,
                    total_tokens=total_tokens,
                    prompt_tokens=prompt_tokens,
                    cached_tokens=cached_tokens,
                    cache_hit_ratio=self.cache_hit_ratio,
                ))

            if session_id and run_id:
                await self._record_run_step(
                    session_id=session_id, task_id=task_id, run_id=run_id,
                    step_type="llm", title="LLM 推理",
                    content=f"上下文消息数: {len(context)}",
                    metadata={"model": self.model, "tools_enabled": bool(tools)},
                    status="ok",
                    duration_ms=duration_ms,
                )

            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)

            # ── 2b. 添加 assistant 消息 ──
            assistant_entry: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if tool_calls:
                assistant_entry["tool_calls"] = [
                    tc.model_dump() if hasattr(tc, "model_dump") else tc
                    for tc in tool_calls
                ]
            context.append(assistant_entry)

            # ── 2c. 无 tool call → 最终答案检查 ──
            if not tool_calls:
                # 空回答恢复
                content = (message.content or "").strip()
                if not content:
                    empty_final_blocks += 1
                    if empty_final_blocks >= _MAX_EMPTY_FINAL_BLOCKS:
                        logger.warning("empty_final_exhausted",
                            agent_id=self.agent_id, blocks=empty_final_blocks)
                        await self._broadcast_status("idle")
                        return "模型连续返回空回答，请检查输入后重试。"
                    context.append({
                        "role": "user",
                        "content": "你返回了空内容。请基于当前信息提供实际的分析结果，不要重复之前的内容。",
                    })
                    self._maybe_compact_context(context)
                    continue

                # 工具使用就绪检查（Reasonix: finalReadinessCheck）
                if tools and not used_any_tool and readiness_blocks < _MAX_READINESS_BLOCKS:
                    readiness_blocks += 1
                    context.append({
                        "role": "user",
                        "content": (
                            "你回答了问题但未使用可用工具。"
                            "请先使用工具收集必要证据后再给出结论，这样结果才是可验证的。"
                        ),
                    })
                    self._maybe_compact_context(context)
                    continue

                await self._broadcast_status("idle")
                return content

            # ── 2d. 有 tool call → 执行 ──
            empty_final_blocks = 0
            used_any_tool = True

            if not tool_executor:
                await self._broadcast_status("idle")
                return message.content or ""

            await self._execute_tool_calls(
                tool_calls, tool_executor=tool_executor,
                context=context,
                session_id=session_id, task_id=task_id, run_id=run_id,
            )

            # ── 2e. 迭代间上下文压缩 ──
            self._maybe_compact_context(context)

        await self._broadcast_status("idle")
        return "已到最大迭代次数，未能生成最终答案。"

    async def _inject_tool_result(
        self,
        context: list[dict[str, Any]],
        tc: Any,
        name: str,
        result: str,
    ) -> None:
        """向上下文注入工具结果（被拦截/出错的工具也需要注入，否则 LLM 会卡住）。"""
        truncated = _truncate_tool_output(result)
        context.append({
            "role": "tool", "tool_call_id": tc.id, "name": name, "content": truncated,
        })
        self._sink.emit(tool_call_event(
            agent_id=self.agent_id,
            tool_name=name,
            arguments={},
            result_preview=result,
            status="error",
            error=result[:200],
            duration_ms=0,
            truncated=len(result) > len(truncated),
        ))

    async def _execute_tool_calls(
        self,
        tool_calls: list[Any],
        *,
        tool_executor: Any,
        context: list[dict[str, Any]],
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """执行一轮工具调用（核心执行逻辑）。

        职责：参数解析 → 中间件拦截 → 安全策略 → executor 执行
              → 中间件响应 → 审计记录 → 上下文注入
        """
        await self._broadcast_status("tool_calling")
        for tc in tool_calls:
            name = tc.function.name
            # ── 工具集权限检查 ──
            if self._allowed_toolsets is not None:
                td = get(name)
                if td and td.toolset not in self._allowed_toolsets:
                    result = json.dumps({
                        "status": "error",
                        "error": f"工具 '{name}' 属于 '{td.toolset}' 工具集，"
                                 f"Agent '{self.agent_id}' 只允许: {self._allowed_toolsets}",
                    }, ensure_ascii=False)
                    await self._inject_tool_result(context, tc, name, result)
                    continue

            started = time.monotonic()
            status = "ok"
            error = None

            # ── 解析参数 ──
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError as exc:
                status = "error"
                error = f"JSON 参数解析失败: {exc}"
                arguments = {}
                result = json.dumps({"status": "error", "error": error}, ensure_ascii=False)
            else:
                # ── 中间件：tool_request（拦截/改写） ──
                mw_result: MiddlewareResult = self._middleware.on_tool_call_request(name, arguments)
                if not mw_result.allowed:
                    status = "error"
                    error = mw_result.reason
                    arguments = mw_result.modified_args or arguments
                    result = json.dumps({"status": "error", "error": error}, ensure_ascii=False)
                else:
                    arguments = mw_result.modified_args or arguments
                    # ── 安全策略检查 ──
                    decision = check_tool_policy(
                        agent_id=self.agent_id, tool_name=name, arguments=arguments,
                    )
                    if not decision.allowed:
                        status = "error"
                        error = decision.reason
                        result = json.dumps({"status": "error", "error": error}, ensure_ascii=False)
                    else:
                        try:
                            result = tool_executor.execute(name, arguments)
                        except Exception as exc:
                            status = "error"
                            error = str(exc)
                            result = json.dumps({"status": "error", "error": error}, ensure_ascii=False)
                        else:
                            # ── 中间件：tool_response（审计/改写） ──
                            duration_ms = int((time.monotonic() - started) * 1000)
                            result = self._middleware.on_tool_call_response(
                                name, arguments, result, duration_ms,
                            )

            duration_ms = int((time.monotonic() - started) * 1000)
            await self._record_tool_call(
                name=name, arguments=arguments, result=result,
                status=status, error=error, duration_ms=duration_ms,
                session_id=session_id, task_id=task_id,
            )
            if session_id and run_id:
                await self._record_run_step(
                    session_id=session_id, task_id=task_id, run_id=run_id,
                    step_type="tool", title=f"工具调用: {name}",
                    content=result[:1000],
                    metadata={"tool_call_id": tc.id, "arguments": arguments},
                    status=status, duration_ms=duration_ms,
                )
            truncated = _truncate_tool_output(result)
            self._sink.emit(tool_call_event(
                agent_id=self.agent_id,
                tool_name=name,
                arguments=arguments,
                result_preview=result,
                status=status,
                error=error,
                duration_ms=duration_ms,
                truncated=len(result) > len(truncated),
            ))
            context.append({
                "role": "tool", "tool_call_id": tc.id, "name": name, "content": truncated,
            })

    def _maybe_compact_context(self, context: list[dict[str, Any]]) -> None:
        """上下文超过阈值时压缩：保留最近 N 轮工具调用。

        参考 Reasonix 的 maybeCompact：移除中间的低价值历史消息，
        保留 system prompt、首条 user 消息和最近 _MAX_CONTEXT_TOOL_ROUNDS 轮。
        """
        if len(context) <= _COMPACT_INTERVAL:
            return
        if len(context) - self._last_compact_len < _COMPACT_INTERVAL:
            return

        # 保留 system + 首条 user
        preserved = context[:2]
        tail_start = max(2, len(context) - _MAX_CONTEXT_TOOL_ROUNDS * 2)
        removed = len(context) - tail_start
        if removed <= 2:
            return

        preserved.append({
            "role": "assistant",
            "content": (
                f"[上下文已压缩，移除了 {removed} 条历史消息，"
                f"保留了最近 {_MAX_CONTEXT_TOOL_ROUNDS} 轮工具调用]"
            ),
        })
        preserved.extend(context[tail_start:])
        context.clear()
        context.extend(preserved)
        self._last_compact_len = len(context)
        logger.debug("context_compacted",
            agent_id=self.agent_id, before=removed + len(preserved), after=len(preserved))

    async def _build_runtime_context(
        self,
        *,
        input_text: str,
        session_id: str | None,
        task_id: str | None,
    ) -> str:
        if not session_id:
            return ""
        build_context = getattr(self.bus, "build_context", None)
        if build_context is None:
            return ""
        try:
            return await build_context(
                session_id=session_id,
                task_id=task_id,
                query=input_text,
            )
        except Exception as exc:
            logger.warning(
                "runtime_context_failed",
                agent_id=self.agent_id,
                error=str(exc)[:120],
            )
            return ""

    def suggest_skills(self, tags: list[str] | None = None, applies_to: str | None = None) -> list[dict]:
        """根据标签和场景从技能库匹配合适的技能（线程安全，非阻塞）。"""
        if self._skill_store is None:
            return []
        matched = self._skill_store.find_by_tags(tags=tags or [], applies_to=applies_to)
        return [s.to_dict() for s in matched]

    def resolve_skills_for_prompt(self, prompt: str) -> list[dict]:
        """针对用户输入解析匹配的技能（Kun 风格评分）。"""
        if self._skill_store is None:
            return []
        resolution = self._skill_store.resolve_turn(
            prompt, tags=self._skill_tags or None, active_limit=3,
        )
        return [
            {"name": m.skill.name, "score": m.score, "reason": m.reason}
            for m in resolution.active
        ]

    async def _record_tool_call(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        result: str,
        status: str,
        error: str | None,
        duration_ms: int,
        session_id: str | None,
        task_id: str | None,
    ) -> None:
        if not session_id:
            return
        add_tool_call = getattr(self.bus, "add_tool_call", None)
        if add_tool_call is None:
            return
        try:
            await add_tool_call(
                ToolCallRecord(
                    session_id=session_id,
                    task_id=task_id,
                    agent_id=self.agent_id,
                    tool_name=name,
                    arguments=arguments,
                    result_preview=result[:500],
                    status=status,
                    error=error,
                    duration_ms=duration_ms,
                    truncated=len(result) > 500,
                )
            )
        except Exception as exc:
            logger.warning(
                "tool_call_audit_failed",
                agent_id=self.agent_id,
                tool=name,
                error=str(exc)[:120],
            )

    async def _record_run_step(
        self,
        *,
        session_id: str,
        task_id: str | None,
        run_id: str,
        step_type: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        status: str = "ok",
        duration_ms: int = 0,
    ) -> None:
        add_run_step = getattr(self.bus, "add_run_step", None)
        if add_run_step is None:
            return
        try:
            await add_run_step(
                RunStepRecord(
                    session_id=session_id,
                    task_id=task_id,
                    run_id=run_id,
                    agent_id=self.agent_id,
                    step_type=step_type,
                    title=title,
                    content=content,
                    metadata=metadata or {},
                    status=status,
                    duration_ms=duration_ms,
                )
            )
        except Exception as exc:
            logger.warning(
                "run_step_audit_failed",
                agent_id=self.agent_id,
                step_type=step_type,
                error=str(exc)[:120],
            )

    async def _call_llm_with_retry(self, max_retries: int = 3, **kwargs) -> Any:
        """Call litellm with retry on transient errors."""
        for attempt in range(max_retries):
            try:
                return await litellm.acompletion(**kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                error_name = type(e).__name__
                if "BadGateway" in error_name or "Timeout" in error_name or "Connection" in error_name:
                    logger.warning("llm_retry", agent_id=self.agent_id, attempt=attempt + 1, error=str(e)[:100])
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    async def send(
        self,
        to: str | None,
        content: str,
        type: str = "conclusion",
        evidence: list[str] | None = None,
        confidence: str = "high",
        reply_to: str | None = None,
        mentions: list[str] | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Send a message through the bus, with optional self-verification.

        If `mentions` is None, @agent_id patterns are auto-parsed from content.
        Pass an explicit list (including empty) to override.
        """
        if mentions is None:
            mentions = self._parse_mentions(content)

        msg = Message(
            from_agent=self.agent_id,
            session_id=session_id or str(uuid4()),
            task_id=task_id,
            run_id=run_id or str(uuid4()),
            to_agent=to,
            mentions=mentions,
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
                        session_id=session_id or msg.session_id,
                        task_id=task_id,
                        run_id=run_id or msg.run_id,
                        to_agent="human",
                        mentions=mentions,
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
                    f"请重新分析并给出修正后的结论。",
                    session_id=session_id or msg.session_id,
                    task_id=task_id,
                    run_id=run_id or msg.run_id,
                )
                # Re-parse mentions from retry response
                retry_mentions = self._parse_mentions(retry_response) if mentions else []
                msg = Message(
                    from_agent=self.agent_id,
                    session_id=session_id or msg.session_id,
                    task_id=task_id,
                    run_id=run_id or msg.run_id,
                    to_agent=to,
                    mentions=retry_mentions,
                    type=type,
                    content=retry_response,
                    evidence=evidence or [],
                    confidence=confidence,
                    reply_to=reply_to,
                )
                hard_verify(msg)

        await self.bus.publish(msg)
