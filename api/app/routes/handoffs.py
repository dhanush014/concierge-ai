"""Staff inbox: list handoffs, read one, join, reply, close (which resumes the agent).
The patient can also leave a handoff themselves (routes/chat.py).

Staff token only. Joining is first come, first served: an active handoff belongs to
the staff member who joined it, and only they can reply or close.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app import handoffs, tracing
from app.agent import config as agent_config
from app.db import Conn
from app.deps import CurrentUser, get_current_staff
from app.models import Handoff, HandoffDetail, Message, StaffMessageRequest
from app.queries import conversation_messages

router = APIRouter(prefix="/staff/handoffs", tags=["staff"])
log = logging.getLogger(__name__)

Staff = Annotated[CurrentUser, Depends(get_current_staff)]

NOT_FOUND = HTTPException(status_code=404, detail="handoff_not_found")
CLOSED_LIMIT = 50  # most recent closed tickets listed

HANDOFF_SELECT = """
    select h.id, h.conversation_id, h.reason, h.summary, h.status, h.staff_id,
           h.created_at, h.closed_at, h.trace_id,
           pt.first_name || ' ' || pt.last_name as patient_name,
           st.display_name as staff_name
    from public.handoffs h
    join public.conversations c on c.id = h.conversation_id
    join public.patients pt on pt.id = c.patient_id
    left join public.profiles st on st.id = h.staff_id
"""


def fetch(conn: psycopg.Connection, handoff_id: UUID, lock: bool = False) -> dict:
    row = conn.execute(
        HANDOFF_SELECT + " where h.id = %s" + (" for update of h" if lock else ""), (handoff_id,)
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    return row


def require_mine(row: dict, staff: CurrentUser) -> None:
    """Replying and closing need an active handoff that this staff member joined."""
    if row["status"] == "closed":
        raise HTTPException(status_code=409, detail="handoff_closed")
    if row["status"] != "active" or row["staff_id"] != staff.id:
        raise HTTPException(status_code=409, detail="not_joined")


@router.get("")
def list_handoffs(
    conn: Conn, staff: Staff, status: Literal["open", "active", "closed"] | None = None
) -> list[Handoff]:
    """Newest first. Closed tickets: the most recent 50."""
    rows = conn.execute(
        HANDOFF_SELECT
        + " where (%(status)s::text is null or h.status = %(status)s)"
        + " order by h.created_at desc",
        {"status": status},
    ).fetchall()
    closed = [r for r in rows if r["status"] == "closed"][:CLOSED_LIMIT]
    return [Handoff(**r) for r in rows if r["status"] != "closed"] + [Handoff(**r) for r in closed]


@router.get("/{handoff_id}")
def get_handoff(conn: Conn, staff: Staff, handoff_id: UUID) -> HandoffDetail:
    row = fetch(conn, handoff_id)
    return HandoffDetail(
        **row,
        messages=conversation_messages(conn, row["conversation_id"]),
        trace_url=tracing.trace_url(row["trace_id"]),
    )


@router.post("/{handoff_id}/join")
def join(conn: Conn, staff: Staff, handoff_id: UUID) -> Handoff:
    row = fetch(conn, handoff_id, lock=True)
    if row["status"] == "active" and row["staff_id"] == staff.id:
        return Handoff(**row)  # already yours: joining again changes nothing
    if row["status"] == "closed":
        raise HTTPException(status_code=409, detail="handoff_closed")
    if row["status"] == "active":
        raise HTTPException(status_code=409, detail="handoff_taken")
    conn.execute("update public.handoffs set status = 'active', staff_id = %s where id = %s", (staff.id, handoff_id))
    handoffs.save_message(
        conn,
        row["conversation_id"],
        "staff",
        agent_config.STAFF_JOINED_NOTICE.format(name=staff.display_name),
        "notice",
        staff.id,
    )
    return Handoff(**fetch(conn, handoff_id))


@router.post("/{handoff_id}/messages", status_code=201)
def send_message(conn: Conn, staff: Staff, handoff_id: UUID, body: StaffMessageRequest) -> Message:
    row = fetch(conn, handoff_id, lock=True)
    require_mine(row, staff)
    message_id = handoffs.save_message(conn, row["conversation_id"], "staff", body.content, "text", staff.id)
    return next(m for m in conversation_messages(conn, row["conversation_id"]) if m.id == message_id)


@router.post("/{handoff_id}/close")
def close(request: Request, conn: Conn, staff: Staff, handoff_id: UUID) -> Handoff:
    """Close the ticket and hand the chat back to the assistant (see handoffs.end_handoff)."""
    row = fetch(conn, handoff_id, lock=True)
    require_mine(row, staff)
    handoffs.end_handoff(request.app.state.chat_graph, conn, row, agent_config.ASSISTANT_BACK_NOTICE)
    return Handoff(**fetch(conn, handoff_id))
