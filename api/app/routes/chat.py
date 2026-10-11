"""Chat with the agent: POST /me/chat streams the reply (SSE), GET returns history.

A conversation that isn't yours gets the same 404 as one that doesn't exist.

Stream events (each `data: <json>`):
  {"type": "conversation", "id": ...}           first, always
  {"type": "token", "text": ...}                 zero or more; join them for the reply
  {"type": "notice", "text": ...}                a system line, e.g. "A nurse has been notified"
  {"type": "done", "safety", "route", "kind", "status"}  last on success;
                                                 status "handoff" = waiting for staff
  {"type": "error", "message": "chat_failed"}    last on failure (patient message is kept)

While a conversation is in handoff the agent stays silent: the patient's message is
saved and staff see it live. One exception: an emergency (regex rules, no LLM) still
gets the 911 message at once, and the ticket is flagged as an emergency.
"""

import json
import logging
import uuid
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import ConnectionPool

from app import handoffs
from app.agent import config as agent_config
from app.agent.graph import turn_input
from app.agent.safety import is_emergency_by_rules
from app.db import Conn
from app.deps import get_current_patient
from app.models import ChatRequest, Conversation
from app.queries import conversation_messages

router = APIRouter(prefix="/me", tags=["chat"])
log = logging.getLogger(__name__)

PatientId = Annotated[UUID, Depends(get_current_patient)]

NOT_FOUND = HTTPException(status_code=404, detail="conversation_not_found")
FIXED_TEXT_NODES = ("escalate", "reply")  # nodes that send a fixed reply, not tokens

# How the reply is shown: red for emergencies, amber when a nurse is being connected.
KIND_FOR_SAFETY = {"emergency": "emergency", "clinical": "handoff", "wants_human": "handoff"}


def owned_conversation(conn: psycopg.Connection, conversation_id: UUID, patient_id: UUID) -> dict:
    row = conn.execute(
        "select id, status, created_at from public.conversations where id = %s and patient_id = %s",
        (conversation_id, patient_id),
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    return row


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def run_turn(
    graph: CompiledStateGraph, pool: ConnectionPool, conversation_id: UUID, patient_id: UUID, message: str
) -> Iterator[str]:
    """Run one graph turn, yielding SSE lines and saving each reply as its node finishes
    (so a 911 message is saved and shown before the handoff is even created).

    Runs after the request's own connection is released, so it saves with its own.
    """
    yield sse({"type": "conversation", "id": str(conversation_id)})
    trace_id = str(uuid.uuid4())  # becomes the LangSmith run id of this turn
    config = {"configurable": {"thread_id": str(conversation_id)}, "run_id": trace_id}
    kind = "text"
    category = "ok"

    def save(content: str, kind: str) -> None:
        with pool.connection() as conn:
            handoffs.save_message(conn, conversation_id, "assistant", content, kind)

    try:
        for mode, data in graph.stream(
            turn_input(patient_id, message, trace_id), config, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                chunk, meta = data
                if meta.get("langgraph_node") == "answer" and isinstance(chunk.content, str) and chunk.content:
                    yield sse({"type": "token", "text": chunk.content})
                continue
            for node, update in data.items():
                if node == "safety_check":
                    category = update["safety"]
                elif node in FIXED_TEXT_NODES:
                    text = update["messages"][-1].content
                    kind = KIND_FOR_SAFETY.get(category, "text")
                    save(text, kind)
                    yield sse({"type": "token", "text": text})
                elif node == "answer":
                    save(update["messages"][-1].content, "text")
                elif node == "create_handoff" and update.get("notice"):
                    save(update["notice"], "notice")
                    yield sse({"type": "notice", "text": update["notice"]})

        state = graph.get_state(config)
        status = "handoff" if state.next else "bot"  # paused at wait_for_staff
        values = state.values
        yield sse({"type": "done", "safety": values["safety"], "route": values.get("route"), "kind": kind, "status": status})
    except Exception:
        log.exception("Chat turn failed for conversation %s", conversation_id)
        yield sse({"type": "error", "message": "chat_failed"})


def handoff_turn(conversation_id: UUID, emergency: bool) -> Iterator[str]:
    """The reply while waiting for staff: nothing, unless it's an emergency."""
    yield sse({"type": "conversation", "id": str(conversation_id)})
    if emergency:
        yield sse({"type": "token", "text": agent_config.EMERGENCY_REPLY})
    kind = "emergency" if emergency else None
    yield sse({"type": "done", "safety": None, "route": None, "kind": kind, "status": "handoff"})


@router.post("/chat")
def chat(request: Request, conn: Conn, patient_id: PatientId, body: ChatRequest) -> StreamingResponse:
    if body.conversation_id is None:
        convo = conn.execute(
            "insert into public.conversations (patient_id) values (%s) returning id, status", (patient_id,)
        ).fetchone()
    else:
        convo = owned_conversation(conn, body.conversation_id, patient_id)
    conversation_id = convo["id"]
    # Saved (committed by the Conn dependency) before streaming starts.
    handoffs.save_message(conn, conversation_id, "patient", body.message)

    if convo["status"] == "handoff":
        live = handoffs.live_handoff(conn, conversation_id)
        emergency = is_emergency_by_rules(body.message)
        if emergency:
            handoffs.save_message(conn, conversation_id, "assistant", agent_config.EMERGENCY_REPLY, "emergency")
            if live is not None:
                handoffs.flag_emergency(conn, live["id"])
        stream = handoff_turn(conversation_id, emergency)
    else:
        stream = run_turn(
            request.app.state.chat_graph, request.app.state.pool, conversation_id, patient_id, body.message
        )
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def with_messages(conn: psycopg.Connection, convo: dict) -> Conversation:
    return Conversation(**convo, messages=conversation_messages(conn, convo["id"]))


# Declared before /conversations/{conversation_id} so "latest" isn't read as an id.
@router.get("/conversations/latest")
def latest_conversation(conn: Conn, patient_id: PatientId) -> Conversation | None:
    """Your newest conversation, or null if you have none. The Ask tab reopens it."""
    convo = conn.execute(
        "select id, status, created_at from public.conversations"
        " where patient_id = %s order by created_at desc, id desc limit 1",
        (patient_id,),
    ).fetchone()
    return None if convo is None else with_messages(conn, convo)


@router.get("/conversations/{conversation_id}")
def get_conversation(conn: Conn, patient_id: PatientId, conversation_id: UUID) -> Conversation:
    return with_messages(conn, owned_conversation(conn, conversation_id, patient_id))
