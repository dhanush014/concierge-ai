from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agent.checkpointer import open_checkpointer
from app.agent.graph import build_graph
from app.agent.llm import check_mode_at_startup
from app.db import db_error_handler, open_pool
from app.routes import appointments, chat, documents


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.llm_mode = check_mode_at_startup()  # refuses to start on a bad LLM_FAKE combo
    app.state.pool = open_pool()
    checkpoint_pool, checkpointer = open_checkpointer()
    app.state.chat_graph = build_graph(app.state.pool, checkpointer)
    try:
        yield
    finally:
        checkpoint_pool.close()
        app.state.pool.close()


# The Next.js dev server is the only browser origin allowed to call the API.
WEB_ORIGINS = ["http://localhost:3000"]

app = FastAPI(title="Concierge AI API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_exception_handler(psycopg.Error, db_error_handler)
app.include_router(appointments.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    # llm: "groq" or "fake"; the E2E setup refuses to run against a real-model API.
    return {"status": "ok", "llm": request.app.state.llm_mode}
