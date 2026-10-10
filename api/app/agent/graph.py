"""The chat agent:

    safety_check --ok--> router --appointments/documents--> tools -> answer
         |                  \\--change_appointment/other--> reply
         \\--emergency/clinical/wants_human--> escalate

escalate and reply send fixed text (no LLM). Only `answer` streams model tokens.
Conversation memory lives in the Postgres checkpointer, one thread per conversation.
In 3.3 escalate becomes the handoff (LangGraph interrupt).
"""

import json
import logging
import re
from typing import Annotated, Literal, TypedDict
from uuid import UUID

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from psycopg_pool import ConnectionPool

from app.agent import config, llm, safety
from app.agent.prompts import ANSWER_PROMPT, ROUTER_PROMPT
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


def _latest_text(state: ChatState) -> str:
    return str(state["messages"][-1].content)


def _recent(state: ChatState) -> list[AnyMessage]:
    return state["messages"][-config.HISTORY_TURNS :]


def safety_check(state: ChatState) -> ChatState:
    result = safety.check(_latest_text(state))
    # route/records reset so a previous turn's values never leak into this one
    return {"safety": result.category, "safety_source": result.source, "route": None, "records": None}


def escalate(state: ChatState) -> ChatState:
    return {"messages": [AIMessage(FIXED_REPLIES[state["safety"]])]}


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
    g.add_node("router", router)
    g.add_node("tools", make_tools_node(pool))
    g.add_node("reply", reply)
    g.add_node("answer", answer)

    g.add_edge(START, "safety_check")
    g.add_conditional_edges("safety_check", after_safety, ["router", "escalate"])
    g.add_conditional_edges("router", after_router, ["tools", "reply"])
    g.add_edge("tools", "answer")
    g.add_edge("escalate", END)
    g.add_edge("reply", END)
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer)


def turn_input(patient_id: UUID, message: str) -> ChatState:
    return {"patient_id": str(patient_id), "messages": [HumanMessage(message)]}
