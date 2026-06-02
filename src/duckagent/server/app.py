"""FastAPI application for the message bus server."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from duckagent.config import settings

from .db import Database
from .routes import router
from .ws_manager import ConnectionManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(settings.db_path)
    await db.connect()
    app.state.db = db
    app.state.ws_manager = ConnectionManager()
    yield
    await db.close()


app = FastAPI(title="DuckAgent Bus Server", version="0.1.0", lifespan=lifespan)
app.include_router(router)
