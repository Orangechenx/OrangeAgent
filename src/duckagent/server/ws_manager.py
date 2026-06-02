"""WebSocket connection manager for the message bus server.

Manages three categories of connections:
- Agent connections (agent_id → WebSocket): receive messages routed to them
- Observer connections: receive ALL messages (TUI message display)
- Status subscribers: receive only status messages (TUI agent cards)
"""

import json
from typing import Any

from fastapi import WebSocket

from duckagent.bus.models import Message


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
        for agent_id in recipients:
            ws = self._agents.get(agent_id)
            if ws:
                await self._safe_send(ws, payload)

        # Observers see everything
        for ws in self._observers:
            await self._safe_send(ws, payload)

        # Status subscribers see only status
        if msg.type == "status":
            for ws in self._status_subs:
                await self._safe_send(ws, payload)

    # --- Helpers ---

    @staticmethod
    def _serialize(msg: Message) -> dict[str, Any]:
        """Serialize a Message to a JSON-safe dict for WebSocket transport."""
        data = msg.model_dump(mode="json")
        return {"type": "message", "data": data}

    @staticmethod
    async def _safe_send(ws: WebSocket, payload: dict[str, Any]) -> None:
        """Send JSON to a WebSocket, ignoring disconnected clients."""
        try:
            await ws.send_json(payload)
        except Exception:
            pass
