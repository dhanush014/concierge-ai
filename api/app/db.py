"""Postgres connection pool and database-error to HTTP mapping."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

log = logging.getLogger(__name__)

# Error names raised by the SQL functions (RAISE EXCEPTION '<name>') -> HTTP status.
ERROR_STATUS: dict[str, int] = {
    "slot_in_past": 400,
    "appointment_in_past": 400,
    "slot_mismatch": 400,
    "same_slot": 400,
    "not_your_appointment": 403,
    "slot_not_found": 404,
    "appointment_not_found": 404,
    "slot_not_open": 409,
    "appointment_not_booked": 409,
}

# The partial unique index is the last line of defence against double booking.
DOUBLE_BOOK_CONSTRAINT = "appointments_one_booked_per_slot"


def load_env() -> None:
    """Load KEY=VALUE lines from the repo-root .env without overriding real env vars."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def database_url() -> str:
    load_env()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL is not set (looked in {ENV_FILE})")
    return url


def open_pool() -> ConnectionPool:
    return ConnectionPool(
        database_url(),
        min_size=1,
        max_size=10,
        kwargs={"options": "-c TimeZone=UTC", "row_factory": dict_row},
        open=True,
    )


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """One connection per request. Commits on success, rolls back on any error."""
    with request.app.state.pool.connection() as conn:
        yield conn


# scope="function": commit/rollback happens before the response is sent, so a 2xx
# always means the change is saved.
Conn = Annotated[psycopg.Connection, Depends(get_conn, scope="function")]


def error_name(exc: psycopg.Error) -> str | None:
    """The mapped error name for a database error, or None if it isn't one we expect."""
    if isinstance(exc, psycopg.errors.UniqueViolation):
        if exc.diag.constraint_name == DOUBLE_BOOK_CONSTRAINT:
            return "slot_not_open"
        return None
    # Our functions raise custom SQLSTATEs starting with PT.
    if (exc.sqlstate or "").startswith("PT") and exc.diag.message_primary in ERROR_STATUS:
        return exc.diag.message_primary
    return None


async def db_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, psycopg.Error)
    name = error_name(exc)
    if name is None:
        # Log the real error for us; never send database text to the client.
        log.error("Unhandled database error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    return JSONResponse(status_code=ERROR_STATUS[name], content={"detail": name})
