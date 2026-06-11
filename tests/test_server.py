"""Tests for the FastAPI message bus server endpoints."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orangeagent.server.db import Database
from orangeagent.server.routes import router
from orangeagent.server.ws_manager import ConnectionManager


def _make_app(db_path):
    """Create a fresh FastAPI app with an isolated database per test."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(db_path=db_path)
        await db.connect()
        app.state.db = db
        app.state.ws_manager = ConnectionManager()
        yield
        await db.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


@pytest.fixture
def client(tmp_path):
    """TestClient with fully isolated database per test."""
    db_path = tmp_path / "test.db"
    app = _make_app(db_path)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def make_msg_dict(**kwargs):
    defaults = {
        "from_agent": "trace_agent",
        "to_agent": "main_agent",
        "mentions": [],
        "type": "conclusion",
        "content": "Test message",
        "evidence": ["line 1"],
        "confidence": "high",
    }
    defaults.update(kwargs)
    return defaults


class TestPublish:
    def test_publish_normal_message(self, client):
        resp = client.post("/api/v1/publish", json=make_msg_dict())
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "id" in resp.json()

    def test_publish_persists_non_status(self, client):
        client.post("/api/v1/publish", json=make_msg_dict(content="persisted"))
        resp = client.get("/api/v1/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_publish_does_not_persist_status(self, client):
        client.post("/api/v1/publish", json=make_msg_dict(type="status", content="thinking"))
        resp = client.get("/api/v1/history")
        messages = resp.json()
        non_status = [m for m in messages if m["type"] != "status"]
        assert len(non_status) == 0

    def test_publish_invalid_message_returns_422(self, client):
        resp = client.post("/api/v1/publish", json={"invalid": "data"})
        assert resp.status_code == 422


class TestHistory:
    def test_history_empty(self, client):
        resp = client.get("/api/v1/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_returns_all(self, client):
        for i in range(3):
            client.post("/api/v1/publish", json=make_msg_dict(content=f"msg {i}"))
        resp = client.get("/api/v1/history")
        assert len(resp.json()) == 3

    def test_history_filter_from_agent(self, client):
        client.post("/api/v1/publish", json=make_msg_dict(from_agent="trace_agent", content="from trace"))
        client.post("/api/v1/publish", json=make_msg_dict(from_agent="main_agent", content="from main"))
        resp = client.get("/api/v1/history?from=trace_agent")
        messages = resp.json()
        assert len(messages) == 1
        assert messages[0]["content"] == "from trace"

    def test_history_filter_type(self, client):
        client.post("/api/v1/publish", json=make_msg_dict(type="conclusion", content="c"))
        client.post("/api/v1/publish", json=make_msg_dict(type="request", content="r"))
        resp = client.get("/api/v1/history?type=request")
        messages = resp.json()
        assert len(messages) == 1
        assert messages[0]["content"] == "r"

    def test_history_respects_limit(self, client):
        for i in range(10):
            client.post("/api/v1/publish", json=make_msg_dict(content=f"msg {i}"))
        resp = client.get("/api/v1/history?limit=3")
        assert len(resp.json()) == 3


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
