"""Chat with the agent: POST /me/chat streams the reply (SSE), GET returns history.

A conversation that isn't yours gets the same 404 as one that doesn't exist.

Stream events (each `data: <json>`):
  {"type": "conversation", "id": ...}           first, always
  {"type": "token", "text": ...}                 one or more; join them for the reply
  {"type": "done", "safety": ..., "route": ...}  last on success
  {"type": "error", "message": "chat_failed"}    last on failure (patient message is kept)
"""

import json
import logging
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import ConnectionPool

from app.agent.graph import turn_input
from app.db import Conn
from app.deps import get_current_patient
from app.models import ChatRequest, Conversation, Message

router = APIRouter(prefix="/me", tags=["chat"])
log = logging.getLogger(__name__)

PatientId = Annotated[UUID, Depends(get_current_patient)]

NOT_FOUND = HTTPException(status_code=404, detail="conversation_not_found")
FIXED_TEXT_NODES = ("escalate", "reply")  # nodes that send a fixed reply, not tokens

INSERT_MESSAGE = (
    "insert into public.messages (conversation_id, sender, content) values (%s, %s, %s)"
)


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
    """Run one graph turn, yielding SSE lines, then save the assistant's reply.

    Runs after the request's own connection is released, so it saves with its own.
    """
    yield sse({"type": "conversation", "id": str(conversation_id)})
    config = {"configurable": {"thread_id": str(conversation_id)}}
    try:
        for mode, data in graph.stream(
            turn_input(patient_id, message), config, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                chunk, meta = data
                if meta.get("langgraph_node") == "answer" and isinstance(chunk.content, str) and chunk.content:
                    yield sse({"type": "token", "text": chunk.content})
            else:
                for node, update in data.items():
                    if node in FIXED_TEXT_NODES:
                        yield sse({"type": "token", "text": update["messages"][-1].content})

        state = graph.get_state(config).values
        with pool.connection() as conn:
            conn.execute(INSERT_MESSAGE, (conversation_id, "assistant", state["messages"][-1].content))
        yield sse({"type": "done", "safety": state["safety"], "route": state.get("route")})
    except Exception:
        log.exception("Chat turn failed for conversation %s", conversation_id)
        yield sse({"type": "error", "message": "chat_failed"})


@router.post("/chat")
def chat(request: Request, conn: Conn, patient_id: PatientId, body: ChatRequest) -> StreamingResponse:
    if body.conversation_id is None:
        conversation_id = conn.execute(
            "insert into public.conversations (patient_id) values (%s) returning id", (patient_id,)
        ).fetchone()["id"]
    else:
        conversation_id = owned_conversation(conn, body.conversation_id, patient_id)["id"]
    # Saved (committed by the Conn dependency) before streaming starts.
    conn.execute(INSERT_MESSAGE, (conversation_id, "patient", body.message))

    stream = run_turn(
        request.app.state.chat_graph, request.app.state.pool, conversation_id, patient_id, body.message
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/conversations/{conversation_id}")
def get_conversation(conn: Conn, patient_id: PatientId, conversation_id: UUID) -> Conversation:
    convo = owned_conversation(conn, conversation_id, patient_id)
    rows = conn.execute(
        "select id, sender, content, created_at from public.messages"
        " where conversation_id = %s order by created_at, id",
        (conversation_id,),
    ).fetchall()
    return Conversation(**convo, messages=[Message(**r) for r in rows])
