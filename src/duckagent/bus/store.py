import asyncio
import json
from pathlib import Path

import aiosqlite

from .models import Message

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT NOT NULL,
    to_agent TEXT,
    mentions TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    reply_to TEXT
)
"""


class MessageBus:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._subscribers: dict[str, asyncio.Queue[Message]] = {}
        self._observers: list[asyncio.Queue[Message]] = []

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        # Migration: add mentions column for databases created before Phase 1
        try:
            await self._db.execute("SELECT mentions FROM messages LIMIT 1")
        except aiosqlite.OperationalError:
            await self._db.execute(
                "ALTER TABLE messages ADD COLUMN mentions TEXT NOT NULL DEFAULT '[]'"
            )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        self._subscribers.clear()
        self._observers.clear()

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._subscribers[agent_id] = queue
        return queue

    def unsubscribe(self, agent_id: str) -> None:
        self._subscribers.pop(agent_id, None)

    def add_observer(self) -> asyncio.Queue[Message]:
        """Subscribe to ALL messages flowing through the bus (observer pattern).

        Returns a queue that receives a copy of every dispatched message.
        Unlike `subscribe`, multiple observers can coexist — they all get copies.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._observers.append(queue)
        return queue

    def remove_observer(self, queue: asyncio.Queue[Message]) -> None:
        """Remove a previously added observer queue."""
        try:
            self._observers.remove(queue)
        except ValueError:
            pass

    async def publish(self, msg: Message) -> None:
        if msg.type != "status":
            await self._persist(msg)
        self._dispatch(msg)

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        query = (
            "SELECT id, from_agent, to_agent, mentions, type, content, "
            "evidence, confidence, timestamp, reply_to "
            "FROM messages WHERE 1=1"
        )
        params: list[str] = []

        if from_agent:
            query += " AND from_agent = ?"
            params.append(from_agent)
        if msg_type:
            query += " AND type = ?"
            params.append(msg_type)

        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(str(limit))

        assert self._db is not None
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    async def _persist(self, msg: Message) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO messages (id, from_agent, to_agent, mentions, type, content, evidence, confidence, timestamp, reply_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
                json.dumps(msg.mentions),
                msg.type,
                msg.content,
                json.dumps(msg.evidence),
                msg.confidence,
                msg.timestamp.isoformat(),
                msg.reply_to,
            ),
        )
        await self._db.commit()

    def _dispatch(self, msg: Message) -> None:
        recipients: set[str] = set()

        # 1. Direct target (backward compat)
        if msg.to_agent:
            recipients.add(msg.to_agent)

        # 2. Mentioned agents (new)
        for agent_id in msg.mentions:
            recipients.add(agent_id)

        # 3. If no explicit recipients, broadcast to all subscribers except sender
        if not recipients:
            for agent_id in self._subscribers:
                if agent_id != msg.from_agent:
                    recipients.add(agent_id)

        # Sender never receives their own message
        recipients.discard(msg.from_agent)

        # Deliver to resolved recipients
        for agent_id in recipients:
            queue = self._subscribers.get(agent_id)
            if queue:
                queue.put_nowait(msg)

        # Push a copy to all observers (TUI sees everything)
        for obs in self._observers:
            obs.put_nowait(msg)

    @staticmethod
    def _row_to_message(row: tuple) -> Message:
        return Message(
            id=row[0],
            from_agent=row[1],
            to_agent=row[2],
            mentions=json.loads(row[3]),
            type=row[4],
            content=row[5],
            evidence=json.loads(row[6]),
            confidence=row[7],
            timestamp=row[8],
            reply_to=row[9],
        )
