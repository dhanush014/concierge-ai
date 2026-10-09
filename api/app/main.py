from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import db_error_handler, open_pool
from app.routes import appointments


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pool = open_pool()
    try:
        yield
    finally:
        app.state.pool.close()


# The Next.js dev server is the only browser origin allowed to call the API.
WEB_ORIGINS = ["http://localhost:3000"]

app = FastAPI(title="Concierge AI API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_exception_handler(psycopg.Error, db_error_handler)
app.include_router(appointments.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
