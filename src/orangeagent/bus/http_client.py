"""HttpMessageBus — HTTP + WebSocket client for the message bus server.

Implements the MessageBus ABC so agent code works unchanged.
Uses httpx for HTTP requests (publish, history) and websockets for
real-time message receipt.

Architecture:
- Agent mode (agent_id set): WebSocket connects as ?agent_id=<id>,
  server pushes only messages routed to this agent.
- Observer mode (agent_id=None): WebSocket connects as ?role=observer,
  server pushes ALL messages (TUI use).

subscribe() and add_observer() create asyncio.Queue objects synchronously
and a background _ws_reader() coroutine fans incoming messages to all queues.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog
import websockets
import websockets.asyncio.client

from orangeagent.config import settings
from orangeagent.runtime.models import (
    EvidenceRecord,
    HandoffRecord,
    MemoryRecord,
    RunRecord,
    RunStepRecord,
    TaskRecord,
    ToolCallRecord,
)

from .interface import MessageBus
from .models import Message

logger = structlog.get_logger()

# How long to wait for server health check on connect / reconnect
_CONNECT_TIMEOUT = 10.0
_DEFAULT_QUEUE_MAXSIZE = 200


class ConnectionError(Exception):
    """Raised when the bus server is unreachable."""


class HttpMessageBus(MessageBus):
    """Message bus client that communicates with the FastAPI server.

    Parameters
    ----------
    server_url:
        Base URL of the bus server, e.g. "http://127.0.0.1:8720".
    agent_id:
        When set, the WebSocket connects in agent mode and only receives
        messages addressed to this agent. When None (default), connects
        in observer mode and receives ALL messages.
    """

    def __init__(
        self,
        server_url: str | None = None,
        agent_id: str | None = None,
        queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
        reconnect_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        reconnect_max_attempts: int | None = None,
    ) -> None:
        self._server_url = (server_url or settings.bus_server_url).rstrip("/")
        self._agent_id = agent_id
        self._http: httpx.AsyncClient | None = None
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._queues: list[asyncio.Queue[Message]] = []
        self._queue_maxsize = queue_maxsize
        self._reconnect_delay = reconnect_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._reconnect_max_attempts = reconnect_max_attempts
        self._reconnect_attempts = 0
        self._sleep = asyncio.sleep
        self._closing = False
        self._connected = False

    # --- MessageBus interface ---

    async def initialize(self) -> None:
        """Connect to the bus server: create HTTP client, open WebSocket."""
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        await self._connect_ws()

    async def close(self) -> None:
        """Disconnect from the bus server and release all resources."""
        self._closing = True
        self._connected = False

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http:
            await self._http.aclose()
            self._http = None

        self._queues.clear()

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        """Create a queue that receives messages for the given agent.

        In agent mode the WebSocket already filters; the returned queue
        receives every message that arrives on the WebSocket.  In observer
        mode ALL messages are fanned out.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues.append(queue)
        return queue

    def unsubscribe(self, agent_id: str) -> None:
        """Remove all queues.  Individual-queue removal is a no-op
        (HttpMessageBus fans out to all queues)."""

    def add_observer(self) -> asyncio.Queue[Message]:
        """Create a queue that receives every message (observer pattern).

        Multiple observers can coexist — each gets a copy.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=self._queue_maxsize)
        self._queues.append(queue)
        return queue

    def remove_observer(self, queue: asyncio.Queue[Message]) -> None:
        """Remove an observer queue."""
        try:
            self._queues.remove(queue)
        except ValueError:
            pass

    async def publish(self, msg: Message) -> None:
        """Publish a message via HTTP POST."""
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/publish",
                json=msg.model_dump(mode="json"),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to publish message: {exc}") from exc

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        """Retrieve historical messages via HTTP GET."""
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if from_agent:
            params["from"] = from_agent
        if msg_type:
            params["type"] = msg_type
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/history",
                params=params,
            )
            resp.raise_for_status()
            return [Message(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch history: {exc}") from exc

    async def get_tasks(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if session_id:
            params["session_id"] = session_id
        try:
            resp = await self._http.get(f"{self._server_url}/api/v1/tasks", params=params)
            resp.raise_for_status()
            return [TaskRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch tasks: {exc}") from exc

    async def get_runs(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if session_id:
            params["session_id"] = session_id
        if task_id:
            params["task_id"] = task_id
        if run_id:
            params["run_id"] = run_id
        try:
            resp = await self._http.get(f"{self._server_url}/api/v1/runs", params=params)
            resp.raise_for_status()
            return [RunRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch runs: {exc}") from exc

    async def get_evidence(self, *, task_id: str, limit: int = 50) -> list[EvidenceRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/evidence",
                params={"task_id": task_id, "limit": str(limit)},
            )
            resp.raise_for_status()
            return [EvidenceRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch evidence: {exc}") from exc

    async def get_memories(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if session_id:
            params["session_id"] = session_id
        if task_id:
            params["task_id"] = task_id
        try:
            resp = await self._http.get(f"{self._server_url}/api/v1/memories", params=params)
            resp.raise_for_status()
            return [MemoryRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch memories: {exc}") from exc

    async def add_memory(self, memory: MemoryRecord) -> MemoryRecord:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/memories",
                json=memory.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return MemoryRecord(**resp.json())
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to add memory: {exc}") from exc

    async def build_context(
        self,
        *,
        session_id: str,
        task_id: str | None,
        query: str,
        limit: int = 8,
    ) -> str:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params = {"session_id": session_id, "query": query, "limit": str(limit)}
        if task_id:
            params["task_id"] = task_id
        try:
            resp = await self._http.get(f"{self._server_url}/api/v1/context", params=params)
            resp.raise_for_status()
            return str(resp.json().get("context", ""))
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to build context: {exc}") from exc

    async def build_system_context(self, *, limit: int = 15) -> str:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/system-context",
                params={"limit": str(limit)},
            )
            resp.raise_for_status()
            return str(resp.json().get("context", ""))
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to build system context: {exc}") from exc

    async def add_tool_call(self, record: ToolCallRecord) -> ToolCallRecord:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/tool-calls",
                json=record.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return ToolCallRecord(**resp.json())
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to add tool call: {exc}") from exc

    async def get_tool_calls(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> list[ToolCallRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if task_id:
            params["task_id"] = task_id
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/tool-calls",
                params=params,
            )
            resp.raise_for_status()
            return [ToolCallRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch tool calls: {exc}") from exc

    async def add_handoff(self, record: HandoffRecord) -> HandoffRecord:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/handoffs",
                json=record.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return HandoffRecord(**resp.json())
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to add handoff: {exc}") from exc

    async def get_handoffs(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[HandoffRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if task_id:
            params["task_id"] = task_id
        if run_id:
            params["run_id"] = run_id
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/handoffs",
                params=params,
            )
            resp.raise_for_status()
            return [HandoffRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch handoffs: {exc}") from exc

    async def add_run_step(self, record: RunStepRecord) -> RunStepRecord:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/run-steps",
                json=record.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return RunStepRecord(**resp.json())
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to add run step: {exc}") from exc

    async def get_run_steps(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[RunStepRecord]:
        if not self._http:
            raise ConnectionError("HttpMessageBus not initialized")
        params: dict[str, str] = {"limit": str(limit)}
        if task_id:
            params["task_id"] = task_id
        if run_id:
            params["run_id"] = run_id
        try:
            resp = await self._http.get(
                f"{self._server_url}/api/v1/run-steps",
                params=params,
            )
            resp.raise_for_status()
            return [RunStepRecord(**item) for item in resp.json()]
        except httpx.HTTPError as exc:
            raise ConnectionError(f"Failed to fetch run steps: {exc}") from exc

    async def cleanup_runtime(self, *, max_memories_per_task: int = 100) -> dict[str, int]:
        if not self._http:
            raise ConnectionError("HttpMessageBus 未初始化")
        try:
            resp = await self._http.post(
                f"{self._server_url}/api/v1/runtime/cleanup",
                params={"max_memories_per_task": str(max_memories_per_task)},
            )
            resp.raise_for_status()
            payload = resp.json()
            return {"archived_memories": int(payload.get("archived_memories", 0))}
        except httpx.HTTPError as exc:
            raise ConnectionError(f"清理 runtime 失败: {exc}") from exc

    # --- WebSocket lifecycle ---

    async def _connect_ws(self) -> None:
        """Open the WebSocket connection and start the reader task.

        Chooses the query param based on agent/observer mode.
        """
        ws_url = self._server_url.replace("http://", "ws://").replace("https://", "wss://")
        if self._agent_id:
            ws_url += f"/ws?agent_id={self._agent_id}"
        else:
            ws_url += "/ws?role=observer"

        self._ws = await websockets.asyncio.client.connect(
            ws_url, open_timeout=_CONNECT_TIMEOUT
        )
        self._connected = True
        self._closing = False
        self._reconnect_attempts = 0
        self._ws_task = asyncio.create_task(self._ws_reader())
        logger.info(
            "http_bus_connected",
            server_url=self._server_url,
            agent_id=self._agent_id or "observer",
        )

    # --- WebSocket reader ---

    async def _ws_reader(self) -> None:
        """Background task: read messages from WebSocket, fan out to all queues.

        Runs until the WebSocket closes or is cancelled.
        """
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    payload: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("ws_bad_json", raw=raw[:200])
                    continue

                if payload.get("type") != "message":
                    continue

                data = payload.get("data")
                if not isinstance(data, dict):
                    continue

                try:
                    msg = Message(**data)
                except Exception:
                    logger.warning("ws_bad_message", data=str(data)[:200])
                    continue

                # Fan out to every registered queue
                for q in self._queues:
                    _put_drop_oldest(q, msg)

        except websockets.ConnectionClosed:
            logger.info("ws_connection_closed", agent_id=self._agent_id or "observer")
        except asyncio.CancelledError:
            pass
        finally:
            self._connected = False
            if not self._closing:
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        delay = self._reconnect_delay
        while not self._closing:
            if (
                self._reconnect_max_attempts is not None
                and self._reconnect_attempts >= self._reconnect_max_attempts
            ):
                return
            await self._sleep(delay)
            if self._closing:
                return
            self._reconnect_attempts += 1
            try:
                await self._connect_ws()
                self._reconnect_attempts = 0
                return
            except Exception as exc:
                logger.warning(
                    "ws_reconnect_failed",
                    agent_id=self._agent_id or "observer",
                    attempt=self._reconnect_attempts,
                    error=str(exc)[:120],
                )
                delay = min(delay * 2, self._reconnect_max_delay)

    async def _reconnect_after_delay(self) -> None:
        await self._reconnect_loop()


def _put_drop_oldest(queue: asyncio.Queue[Message], msg: Message) -> None:
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(msg)
