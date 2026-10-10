"""LangGraph's Postgres checkpointer, kept in its own `langgraph` schema.

Migration 0005 creates the schema. The library creates and upgrades its own tables in
it (setup() is idempotent), so its internal layout never ends up in our migrations.
"""

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

from app.db import database_url

SCHEMA = "langgraph"


def open_checkpointer() -> tuple[ConnectionPool, PostgresSaver]:
    # The library needs autocommit and dict rows; prepare_threshold=0 keeps it working
    # behind poolers that don't support prepared statements.
    pool = ConnectionPool(
        database_url(),
        min_size=1,
        max_size=5,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={SCHEMA}",
        },
        open=True,
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return pool, saver
