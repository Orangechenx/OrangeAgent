"""WebSocket connection manager for the message bus server.

Manages three categories of connections:
- Agent connections (agent_id → WebSocket): receive messages routed to them
- Observer connections: receive ALL messages (TUI message display)
- Status subscribers: receive only status messages (TUI agent cards)
"""

import json
from typing import Any

from fastapi import WebSocket
import structlog

from orangeagent.bus.models import Message

logger = structlog.get_logger()


class ConnectionManager:
    """Tracks WebSocket connections and dispatches messages to the right ones."""

    def __init__(self) -> None:
        self._agents: dict[str, WebSocket] = {}
        self._observers: list[WebSocket] = []
        self._status_subs: list[WebSocket] = []

    # --- Connection lifecycle ---

    async def connect_agent(self, ws: WebSocket, agent_id: str) -> None:
        await ws.accept()
        self._agents[agent_id] = ws

    def disconnect_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    async def connect_observer(self, ws: WebSocket) -> None:
        await ws.accept()
        self._observers.append(ws)

    def disconnect_observer(self, ws: WebSocket) -> None:
        try:
            self._observers.remove(ws)
        except ValueError:
            pass

    async def connect_status(self, ws: WebSocket) -> None:
        await ws.accept()
        self._status_subs.append(ws)

    def disconnect_status(self, ws: WebSocket) -> None:
        try:
            self._status_subs.remove(ws)
        except ValueError:
            pass

    # --- Properties ---

    @property
    def active_agent_ids(self) -> set[str]:
        return set(self._agents.keys())

    # --- Dispatch ---

    async def dispatch(self, msg: Message, recipients: set[str]) -> None:
        """Push a message to all relevant WebSocket connections.

        - Recipient agents get it
        - Observers get ALL messages
        - Status subscribers get only status messages
        """
        payload = self._serialize(msg)

        # Push to resolved recipient agents
        dead_agents: list[str] = []
        for agent_id in recipients:
            ws = self._agents.get(agent_id)
            if ws:
                ok = await self._safe_send(ws, payload, label=f"agent:{agent_id}")
                if not ok:
                    dead_agents.append(agent_id)
        for agent_id in dead_agents:
            self.disconnect_agent(agent_id)

        # Observers see everything
        dead_observers: list[WebSocket] = []
        for ws in list(self._observers):
            ok = await self._safe_send(ws, payload, label="observer")
            if not ok:
                dead_observers.append(ws)
        for ws in dead_observers:
            self.disconnect_observer(ws)

        # Status subscribers see only status
        if msg.type == "status":
            dead_status: list[WebSocket] = []
            for ws in list(self._status_subs):
                ok = await self._safe_send(ws, payload, label="status")
                if not ok:
                    dead_status.append(ws)
            for ws in dead_status:
                self.disconnect_status(ws)

    # --- Helpers ---

    @staticmethod
    def _serialize(msg: Message) -> dict[str, Any]:
        """Serialize a Message to a JSON-safe dict for WebSocket transport."""
        data = msg.model_dump(mode="json")
        return {"type": "message", "data": data}

    @staticmethod
    async def _safe_send(ws: WebSocket, payload: dict[str, Any], *, label: str) -> bool:
        """发送 WebSocket 消息；失败时由调用方清理连接。"""
        try:
            await ws.send_json(payload)
            return True
        except Exception as exc:
            logger.warning("websocket_send_failed", connection=label, error=str(exc)[:120])
            return False
