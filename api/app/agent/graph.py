"""The chat agent:

    safety_check --ok--> router --appointments/documents--> tools -> answer
         |                  \\--change_appointment/other--> reply
         \\--emergency/clinical/wants_human--> escalate -> create_handoff -> wait_for_staff

escalate and reply send fixed text (no LLM). Only `answer` streams model tokens.
escalate runs first so the 911 message never waits for the summary model.
wait_for_staff pauses the graph (interrupt) until staff close the handoff; the close
endpoint resumes it with the handoff transcript.
Conversation memory lives in the Postgres checkpointer, one thread per conversation.
"""

import json
import logging
import re
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from psycopg_pool import ConnectionPool

from app import handoffs
from app.agent import config, llm, safety
from app.agent.config import NURSE_NOTIFIED_NOTICE
from app.agent.prompts import ANSWER_PROMPT, ROUTER_PROMPT, SUMMARY_PROMPT
from app.agent.tools import TOOLS

log = logging.getLogger(__name__)

Route = Literal["appointments", "documents", "change_appointment", "other"]
ROUTES: tuple[Route, ...] = ("appointments", "documents", "change_appointment", "other")

FIXED_REPLIES: dict[str, str] = {
    "emergency": config.EMERGENCY_REPLY,
    "clinical": config.NURSE_REPLY,
    "wants_human": config.NURSE_REPLY,
    "change_appointment": config.CHANGE_APPOINTMENT_REPLY,
    "other": config.OTHER_REPLY,
}


class ChatState(TypedDict, total=False):
    patient_id: str  # from the login token, set by the chat route; never from the LLM
    messages: Annotated[list[AnyMessage], add_messages]
    safety: safety.Category
    safety_source: safety.Source
    route: Route | None
    records: str | None
    trace_id: str | None  # LangSmith run id of this turn, stored on a handoff
    notice: str | None  # a notice line for the patient (set by create_handoff)


def _latest_text(state: ChatState) -> str:
    return str(state["messages"][-1].content)


def _recent(state: ChatState) -> list[AnyMessage]:
    return state["messages"][-config.HISTORY_TURNS :]


def safety_check(state: ChatState) -> ChatState:
    result = safety.check(_latest_text(state))
    # route/records reset so a previous turn's values never leak into this one
    return {"safety": result.category, "safety_source": result.source, "route": None, "records": None, "notice": None}


def escalate(state: ChatState) -> ChatState:
    return {"messages": [AIMessage(FIXED_REPLIES[state["safety"]])]}


def summarize(state: ChatState) -> str:
    """One line for the nurse. Never blocks the handoff: falls back to a quote."""
    try:
        reply = llm.chat_model("summary").invoke([SystemMessage(SUMMARY_PROMPT), *_recent(state)])
        text = str(reply.content).strip()
        if text:
            return text[:500]
    except Exception as exc:  # noqa: BLE001
        log.warning("Summary LLM failed (%s); quoting the patient", type(exc).__name__)
    last = next(str(m.content) for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
    return f'Patient wrote: "{last[:300]}"'


def make_create_handoff_node(pool: ConnectionPool):
    # The parameter must be named `config` for LangGraph to pass the run config in.
    def create_handoff(state: ChatState, config: RunnableConfig) -> ChatState:  # noqa: F811
        """All side effects of a handoff live here, NOT in wait_for_staff: LangGraph
        re-runs an interrupted node from the top when it resumes."""
        conversation_id = UUID(config["configurable"]["thread_id"])
        summary = summarize(state)
        with pool.connection() as conn:
            handoffs.open_handoff(conn, conversation_id, state["safety"], summary, state.get("trace_id"))
        notice = NURSE_NOTIFIED_NOTICE if state["safety"] == "emergency" else None
        return {"notice": notice}

    return create_handoff


def wait_for_staff(state: ChatState) -> ChatState:
    """Pause until staff close the handoff. The resume value is what the patient and
    staff wrote meanwhile; it goes into memory so later answers have the context."""
    transcript = interrupt({"waiting_for": "staff"}) or []
    said: list[AnyMessage] = []
    for m in transcript:
        if m["sender"] == "patient":
            said.append(HumanMessage(m["content"]))
        else:
            said.append(AIMessage(f"{m.get('staff_name') or 'Staff'}: {m['content']}"))
    return {"messages": [*said, AIMessage(config.ASSISTANT_BACK_NOTICE)]}


def router(state: ChatState) -> ChatState:
    """LLM picks a route from a fixed list; any failure or junk falls back to 'other'."""
    try:
        model = llm.chat_model("router").bind(response_format={"type": "json_object"})
        reply = model.invoke([SystemMessage(ROUTER_PROMPT), *_recent(state)])
        match = re.search(r"\{.*\}", str(reply.content), re.DOTALL)
        route = json.loads(match.group(0) if match else str(reply.content)).get("route")
    except Exception as exc:  # noqa: BLE001 - a router outage downgrades, never crashes
        log.warning("Router LLM failed (%s); using 'other'", type(exc).__name__)
        route = None
    return {"route": route if route in ROUTES else "other"}


def reply(state: ChatState) -> ChatState:
    return {"messages": [AIMessage(FIXED_REPLIES[state["route"]])]}


def make_tools_node(pool: ConnectionPool):
    def tools(state: ChatState) -> ChatState:
        tool = TOOLS[state["route"]]
        with pool.connection() as conn:
            return {"records": tool(conn, UUID(state["patient_id"]))}

    return tools


def answer(state: ChatState) -> ChatState:
    model = llm.chat_model("answer")
    prompt = SystemMessage(ANSWER_PROMPT.format(records=state["records"]))
    return {"messages": [model.invoke([prompt, *_recent(state)])]}


def after_safety(state: ChatState) -> str:
    return "router" if state["safety"] == "ok" else "escalate"


def after_router(state: ChatState) -> str:
    return "tools" if state["route"] in TOOLS else "reply"


def build_graph(pool: ConnectionPool, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    g = StateGraph(ChatState)
    g.add_node("safety_check", safety_check)
    g.add_node("escalate", escalate)
    g.add_node("create_handoff", make_create_handoff_node(pool))
    g.add_node("wait_for_staff", wait_for_staff)
    g.add_node("router", router)
    g.add_node("tools", make_tools_node(pool))
    g.add_node("reply", reply)
    g.add_node("answer", answer)

    g.add_edge(START, "safety_check")
    g.add_conditional_edges("safety_check", after_safety, ["router", "escalate"])
    g.add_conditional_edges("router", after_router, ["tools", "reply"])
    g.add_edge("tools", "answer")
    g.add_edge("escalate", "create_handoff")
    g.add_edge("create_handoff", "wait_for_staff")
    g.add_edge("wait_for_staff", END)
    g.add_edge("reply", END)
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer)


def turn_input(patient_id: UUID, message: str, trace_id: str | None = None) -> ChatState:
    return {"patient_id": str(patient_id), "messages": [HumanMessage(message)], "trace_id": trace_id}
