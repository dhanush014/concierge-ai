"""Handoff and message writes, shared by the graph, the patient chat route and the
staff routes. Plain SQL. The one-live-handoff rule is a database index.
"""

from typing import Literal
from uuid import UUID

import psycopg

Sender = Literal["patient", "assistant", "staff"]
Kind = Literal["text", "emergency", "handoff", "notice"]
Reason = Literal["emergency", "clinical", "wants_human"]

HANDOFF_COLUMNS = "id, conversation_id, reason, summary, status, staff_id, trace_id, created_at, closed_at"


def save_message(
    conn: psycopg.Connection,
    conversation_id: UUID,
    sender: Sender,
    content: str,
    kind: Kind = "text",
    staff_id: UUID | None = None,
) -> UUID:
    # clock_timestamp(), not the default now(): several messages saved in one
    # transaction must still sort in the order they were written.
    return conn.execute(
        "insert into public.messages (conversation_id, sender, content, kind, staff_id, created_at)"
        " values (%s, %s, %s, %s, %s, clock_timestamp()) returning id",
        (conversation_id, sender, content, kind, staff_id),
    ).fetchone()["id"]


def live_handoff(conn: psycopg.Connection, conversation_id: UUID) -> dict | None:
    """The conversation's open or active handoff, if any."""
    return conn.execute(
        f"select {HANDOFF_COLUMNS} from public.handoffs"
        " where conversation_id = %s and status in ('open', 'active')",
        (conversation_id,),
    ).fetchone()


def open_handoff(
    conn: psycopg.Connection, conversation_id: UUID, reason: Reason, summary: str, trace_id: str | None
) -> tuple[dict, bool]:
    """Create the handoff and put the conversation in 'handoff'. If one is already open
    or active (a race, or a retry) return that one instead: (handoff, created)."""
    row = conn.execute(
        "insert into public.handoffs (conversation_id, reason, summary, trace_id)"
        " values (%s, %s, %s, %s)"
        " on conflict (conversation_id) where status in ('open', 'active') do nothing"
        f" returning {HANDOFF_COLUMNS}",
        (conversation_id, reason, summary, trace_id),
    ).fetchone()
    conn.execute("update public.conversations set status = 'handoff' where id = %s", (conversation_id,))
    if row is not None:
        return row, True
    return live_handoff(conn, conversation_id), False


def flag_emergency(conn: psycopg.Connection, handoff_id: UUID) -> None:
    """An emergency while waiting for staff moves the ticket to the top reason."""
    conn.execute("update public.handoffs set reason = 'emergency' where id = %s", (handoff_id,))


def transcript_since(conn: psycopg.Connection, handoff: dict) -> list[dict]:
    """What the patient and staff wrote during the handoff, oldest first. Handed to
    the graph on close so the assistant remembers it."""
    return conn.execute(
        "select m.sender, m.content, p.display_name as staff_name"
        " from public.messages m left join public.profiles p on p.id = m.staff_id"
        " where m.conversation_id = %s and m.created_at >= %s"
        " and m.sender in ('patient', 'staff') and m.kind = 'text'"
        " order by m.created_at, m.id",
        (handoff["conversation_id"], handoff["created_at"]),
    ).fetchall()
