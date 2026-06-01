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

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
        self._subscribers.clear()

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._subscribers[agent_id] = queue
        return queue

    def unsubscribe(self, agent_id: str) -> None:
        self._subscribers.pop(agent_id, None)

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
        query = "SELECT * FROM messages WHERE 1=1"
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
            "INSERT INTO messages (id, from_agent, to_agent, type, content, evidence, confidence, timestamp, reply_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
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
        if msg.to_agent:
            queue = self._subscribers.get(msg.to_agent)
            if queue:
                queue.put_nowait(msg)
        else:
            for agent_id, queue in self._subscribers.items():
                if agent_id != msg.from_agent:
                    queue.put_nowait(msg)

    @staticmethod
    def _row_to_message(row: tuple) -> Message:
        return Message(
            id=row[0],
            from_agent=row[1],
            to_agent=row[2],
            type=row[3],
            content=row[4],
            evidence=json.loads(row[5]),
            confidence=row[6],
            timestamp=row[7],
            reply_to=row[8],
        )
