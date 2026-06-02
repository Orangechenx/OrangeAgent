"""SQLite persistence layer for the message bus server.

Extracted from duckagent.bus.store to be shared between LocalMessageBus
and the FastAPI server — same schema, same row-to-message mapping.
"""

import json
from pathlib import Path

import aiosqlite

from duckagent.bus.models import Message

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


class Database:
    """Thin wrapper around aiosqlite for message persistence."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        # Migration: add mentions column for old databases
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

    async def insert_message(self, msg: Message) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO messages (id, from_agent, to_agent, mentions, type, "
            "content, evidence, confidence, timestamp, reply_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    async def get_history(
        self,
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]:
        assert self._db is not None
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

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

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
