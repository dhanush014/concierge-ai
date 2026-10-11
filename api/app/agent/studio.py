"""Entry point for LangGraph Studio (`langgraph dev`, see api/langgraph.json). Dev only.

The same nodes and edges as production (graph.add_agent), with three differences:
- No Postgres checkpointer: Studio brings its own (in memory).
- A first step, use_studio_patient, takes the patient id from Studio's context panel
  (default: the demo patient Aja) instead of a login token, so tools return real
  records from the local database.
- Handoffs aren't written to the database (Studio threads aren't our conversations);
  the graph still pauses at wait_for_staff, and the summary is in the state.

Uses the fake LLM unless GROQ_API_KEY is set in the repo .env.
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime

from app.db import load_env, open_pool

load_env()
if not os.environ.get("GROQ_API_KEY"):
    # Free, offline replies. llm.py only allows fake mode together with APP_ENV=local.
    os.environ["LLM_FAKE"] = "1"
    os.environ["APP_ENV"] = "local"

from app.agent.graph import ChatState, add_agent  # noqa: E402 - after the env is set

DEFAULT_PATIENT_EMAIL = "aja.casper@demo.concierge.test"  # seeded by scripts/seed.py

pool = open_pool()


@dataclass
class StudioContext:
    """Shown in Studio's context panel. Leave patient_id empty for Aja."""

    patient_id: str = field(default="", metadata={"description": "Patient UUID; empty = Aja Casper"})


class StudioInput(TypedDict):
    """Studio's input form: just the chat message(s)."""

    messages: Annotated[list[AnyMessage], add_messages]


@lru_cache(maxsize=1)
def default_patient_id() -> str:
    with pool.connection() as conn:
        row = conn.execute(
            "select p.patient_id from public.profiles p join auth.users u on u.id = p.id where u.email = %s",
            (DEFAULT_PATIENT_EMAIL,),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"{DEFAULT_PATIENT_EMAIL} not found: run `uv run scripts/seed.py` first")
    return str(row["patient_id"])


def use_studio_patient(state: ChatState, runtime: Runtime[StudioContext]) -> ChatState:
    """Stands in for the login token: whose records the tools may read."""
    chosen = runtime.context.patient_id if runtime.context else ""
    return {"patient_id": chosen.strip() or default_patient_id()}


def build_studio_graph():
    g = StateGraph(ChatState, context_schema=StudioContext, input_schema=StudioInput)
    add_agent(g, pool, record_handoffs=False)
    g.add_node("use_studio_patient", use_studio_patient)
    g.add_edge(START, "use_studio_patient")
    g.add_edge("use_studio_patient", "safety_check")
    return g.compile()  # no checkpointer: Studio provides one


graph = build_studio_graph()
