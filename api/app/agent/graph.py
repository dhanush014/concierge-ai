"""The chat agent:

    safety_check --ok--> agent <-> tools      (at most MAX_TOOL_CALLS tool calls a turn)
         \\--emergency/clinical/wants_human--> escalate -> create_handoff -> wait_for_staff

`agent` is the LLM with read-only tools (toolkit.py): it calls tools until it has what
it needs, then answers, citing source tags. After MAX_TOOL_CALLS calls it is called
without tools, so it must answer. The patient id reaches tools from state (set from the
login), never from the LLM.
escalate sends fixed text (no LLM) first, so the 911 message never waits for the summary
model. wait_for_staff pauses the graph (interrupt) until staff close the handoff; the
close endpoint resumes it with the handoff transcript.
Conversation memory lives in the Postgres checkpointer, one thread per conversation.
"""

import logging
from typing import Annotated, TypedDict
from uuid import UUID

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from psycopg_pool import ConnectionPool

from app import handoffs
from app.agent import config, llm, safety
from app.agent.config import MAX_TOOL_CALLS, NURSE_NOTIFIED_NOTICE
from app.agent.prompts import AGENT_PROMPT, SUMMARY_PROMPT
from app.agent.toolkit import make_tools

log = logging.getLogger(__name__)

FIXED_REPLIES: dict[str, str] = {
    "emergency": config.EMERGENCY_REPLY,
    "clinical": config.NURSE_REPLY,
    "wants_human": config.NURSE_REPLY,
}


class ChatState(TypedDict, total=False):
    patient_id: str  # from the login token, set by the chat route; never from the LLM
    messages: Annotated[list[AnyMessage], add_messages]
    safety: safety.Category
    safety_source: safety.Source
    trace_id: str | None  # LangSmith run id of this turn, stored on a handoff
    notice: str | None  # a notice line for the patient (set by create_handoff)
    handoff_summary: str | None  # the AI summary staff see (set by create_handoff)


def split_turn(messages: list[AnyMessage]) -> tuple[list[AnyMessage], list[AnyMessage]]:
    """(earlier questions and answers, this turn). This turn starts at the latest patient
    message and includes its tool calls and results. Earlier turns keep only the plain
    questions and answers: their tool traffic is done, and a tool result without the
    call that asked for it is rejected by the API."""
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    earlier = [m for m in messages[:start]
               if isinstance(m, HumanMessage) or (isinstance(m, AIMessage) and not m.tool_calls)]
    return earlier[-config.HISTORY_TURNS :], messages[start:]


def tool_calls_used(turn: list[AnyMessage]) -> int:
    return sum(len(m.tool_calls) for m in turn if isinstance(m, AIMessage))


def turn_tool_messages(messages: list[AnyMessage]) -> list[ToolMessage]:
    """This turn's tool results (their artifacts are the sources)."""
    return [m for m in split_turn(messages)[1] if isinstance(m, ToolMessage)]


def safety_check(state: ChatState) -> ChatState:
    result = safety.check(str(state["messages"][-1].content))
    # reset per-turn values so a previous turn's never leak into this one
    return {"safety": result.category, "safety_source": result.source, "notice": None, "handoff_summary": None}


def escalate(state: ChatState) -> ChatState:
    return {"messages": [AIMessage(FIXED_REPLIES[state["safety"]])]}


def summarize(state: ChatState) -> str:
    """One line for the nurse. Never blocks the handoff: falls back to a quote."""
    try:
        earlier, turn = split_turn(state["messages"])
        reply = llm.chat_model("summary").invoke([SystemMessage(SUMMARY_PROMPT), *earlier, turn[0]])
        text = str(reply.content).strip()
        if text:
            return text[:500]
    except Exception as exc:  # noqa: BLE001
        log.warning("Summary LLM failed (%s); quoting the patient", type(exc).__name__)
    last = next(str(m.content) for m in reversed(state["messages"]) if isinstance(m, HumanMessage))
    return f'Patient wrote: "{last[:300]}"'


def make_create_handoff_node(pool: ConnectionPool, record: bool = True):
    """record=False (LangGraph Studio): its threads aren't conversations in our database,
    so the handoff row is skipped; the summary still lands in the state to inspect."""

    # The parameter must be named `config` for LangGraph to pass the run config in.
    def create_handoff(state: ChatState, config: RunnableConfig) -> ChatState:  # noqa: F811
        """All side effects of a handoff live here, NOT in wait_for_staff: LangGraph
        re-runs an interrupted node from the top when it resumes."""
        summary = summarize(state)
        if record:
            conversation_id = UUID(config["configurable"]["thread_id"])
            with pool.connection() as conn:
                handoffs.open_handoff(conn, conversation_id, state["safety"], summary, state.get("trace_id"))
        notice = NURSE_NOTIFIED_NOTICE if state["safety"] == "emergency" else None
        return {"notice": notice, "handoff_summary": summary}

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


def make_agent_node(tools: list[BaseTool]):
    def agent(state: ChatState) -> ChatState:
        """One LLM step: call tools, or answer. Out of tool budget -> no tools offered."""
        earlier, turn = split_turn(state["messages"])
        remaining = MAX_TOOL_CALLS - tool_calls_used(turn)
        model = llm.chat_model("agent")
        if remaining > 0:
            model = model.bind_tools(tools)
        reply = model.invoke([SystemMessage(AGENT_PROMPT), *earlier, *turn])
        if isinstance(reply, AIMessage) and len(reply.tool_calls) > remaining:
            reply.tool_calls = reply.tool_calls[: max(remaining, 0)]  # never exceed the budget
        return {"messages": [reply]}

    return agent


# Branch names double as the edge labels in the Mermaid diagram (docs/agent-graph.md).
SAFE, NEEDS_PERSON = "ok", "emergency / clinical / wants_human"
CALLS_TOOLS, ANSWERS = "calls tools", "answers"


def after_safety(state: ChatState) -> str:
    return SAFE if state["safety"] == "ok" else NEEDS_PERSON


def after_agent(state: ChatState) -> str:
    last = state["messages"][-1]
    return CALLS_TOOLS if isinstance(last, AIMessage) and last.tool_calls else ANSWERS


def add_agent(g: StateGraph, pool: ConnectionPool, *, record_handoffs: bool = True) -> StateGraph:
    """Every node and edge of the agent, starting at safety_check. Callers add the edge
    into safety_check: START in production, a setup step in LangGraph Studio."""
    tools = make_tools(pool)
    g.add_node("safety_check", safety_check)
    g.add_node("escalate", escalate)
    g.add_node("create_handoff", make_create_handoff_node(pool, record=record_handoffs))
    g.add_node("wait_for_staff", wait_for_staff)
    g.add_node("agent", make_agent_node(tools))
    g.add_node("tools", ToolNode(tools))

    g.add_conditional_edges("safety_check", after_safety, {SAFE: "agent", NEEDS_PERSON: "escalate"})
    g.add_conditional_edges("agent", after_agent, {CALLS_TOOLS: "tools", ANSWERS: END})
    g.add_edge("tools", "agent")
    g.add_edge("escalate", "create_handoff")
    g.add_edge("create_handoff", "wait_for_staff")
    g.add_edge("wait_for_staff", END)
    return g


def build_graph(pool: ConnectionPool, checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
    g = add_agent(StateGraph(ChatState), pool)
    g.add_edge(START, "safety_check")
    return g.compile(checkpointer=checkpointer)


def turn_input(patient_id: UUID, message: str, trace_id: str | None = None) -> ChatState:
    return {"patient_id": str(patient_id), "messages": [HumanMessage(message)], "trace_id": trace_id}
