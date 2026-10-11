"""The LangGraph agent: escalations, the tool loop, the tool budget, the injected
patient id, memory. Fake LLM only."""

import re
import uuid
from collections.abc import Iterator
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import config
from app.agent.graph import turn_input
from app.agent.toolkit import make_tools
from app.agent.tools import appointment_lines, document_lines
from tests.conftest import Factory
from tests.fake_llm import FakeLLM, call

TOOL_NAMES = ["get_my_appointments", "get_my_documents", "get_lab_results", "list_my_records",
              "search_my_records", "search_hospital_policies"]


@pytest.fixture
def graph(client: TestClient):
    return client.app.state.chat_graph


@pytest.fixture
def thread(db: psycopg.Connection) -> Iterator[dict]:
    """A real conversation to run the graph on (handoffs reference it). Owned by a
    throwaway patient row; deleting it clears the graph state too (trigger)."""
    patient = db.execute(
        "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
        " values (%s, 'Graph', 'Test', '1990-01-01') returning id",
        (f"graph-test-{uuid.uuid4().hex[:8]}",),
    ).fetchone()["id"]
    convo = db.execute(
        "insert into public.conversations (patient_id) values (%s) returning id", (patient,)
    ).fetchone()["id"]
    yield {"configurable": {"thread_id": str(convo)}}
    db.execute("delete from public.conversations where id = %s", (convo,))
    db.execute("delete from public.patients where id = %s", (patient,))


def ask(graph, thread: dict, patient_id: uuid.UUID, text: str) -> dict:
    return graph.invoke(turn_input(patient_id, text), thread)


def tool_messages(state: dict) -> list[ToolMessage]:
    return [m for m in state["messages"] if isinstance(m, ToolMessage)]


# --- safety categories end the turn with a fixed reply; the agent never runs ---

@pytest.mark.parametrize(
    ("text", "category", "reply"),
    [
        ("I can't breathe", "emergency", config.EMERGENCY_REPLY),
        ("I feel dizzy", "clinical", config.NURSE_REPLY),
        ("can I talk to a real person", "wants_human", config.NURSE_REPLY),
    ],
)
def test_escalations_reply_fixed_text(graph, thread, make: Factory, fake_llm: FakeLLM, text, category, reply) -> None:
    state = ask(graph, thread, make.patient(), text)
    assert state["safety"] == category
    assert state["messages"][-1].content == reply
    assert fake_llm.calls("agent") == 0


# --- the tool loop ---

def test_answers_without_tools(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.replies["agent"] = "I can help with your records, appointments and documents."
    state = ask(graph, thread, make.patient(), "hello")
    assert state["messages"][-1].content == fake_llm.replies["agent"]
    assert tool_messages(state) == []
    assert fake_llm.bound_tools == [TOOL_NAMES]  # all six offered


@pytest.fixture
def aja_and_bart(make: Factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Aja and Bart, each with one upcoming and one past appointment and a document."""
    patients = []
    for name in ("Aja", "Bart"):
        patient = make.patient()
        doctor = make.doctor(specialty=f"{name} Specialty")
        make.book_directly(patient, make.slot(doctor, timedelta(days=2), visit_type=f"{name} Upcoming"))
        make.book_directly(patient, make.slot(doctor, timedelta(days=-2), visit_type=f"{name} Past"))
        make.document_row(patient, f"{name.lower()}-card.png")
        patients.append(patient)
    return patients[0], patients[1]


def test_tool_call_then_answer_with_sources(graph, thread, aja_and_bart, fake_llm: FakeLLM) -> None:
    aja, _ = aja_and_bart
    fake_llm.agent_script = [call("get_my_appointments"), AIMessage("Your next visit is Aja Upcoming.")]
    state = ask(graph, thread, aja, "when is my next appointment?")
    [result] = tool_messages(state)
    assert "Aja Upcoming" in result.content and "Bart" not in result.content
    assert re.search(r"\[S-[0-9a-f]{4}\] Upcoming appointment", result.content)  # tagged lines
    assert {s["kind"] for s in result.artifact} == {"appointment"}  # sources ride along
    # The second agent call saw the tool result.
    assert any(isinstance(m, ToolMessage) for m in fake_llm.prompts["agent"][1])
    assert state["messages"][-1].content == "Your next visit is Aja Upcoming."


def test_patient_id_comes_from_the_login_not_the_llm(graph, thread, aja_and_bart, fake_llm: FakeLLM) -> None:
    aja, bart = aja_and_bart
    # The LLM tries to pass Bart's id; the injected login id (Aja) wins.
    fake_llm.agent_script = [call("get_my_documents", patient_id=str(bart)), AIMessage("done")]
    [result] = tool_messages(ask(graph, thread, aja, "my documents"))
    assert "aja-card.png" in result.content and "bart" not in result.content


def test_tool_schemas_hide_the_patient_id() -> None:
    for t in make_tools(None):
        assert "patient_id" not in t.tool_call_schema.model_json_schema().get("properties", {}), t.name


def test_at_most_four_tool_calls_then_it_must_answer(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.agent_script = [call("get_my_documents") for _ in range(config.MAX_TOOL_CALLS)]
    fake_llm.agent_script += [AIMessage("final")]
    state = ask(graph, thread, make.patient(), "everything please")
    assert len(tool_messages(state)) == config.MAX_TOOL_CALLS
    assert fake_llm.bound_tools[-1] == []  # the last call offered no tools
    assert state["messages"][-1].content == "final"


def test_a_tool_call_after_the_budget_is_dropped(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    # Even if the model asks for a fifth call with no tools offered, it isn't run.
    fake_llm.agent_script = [call("get_my_documents") for _ in range(config.MAX_TOOL_CALLS + 1)]
    state = ask(graph, thread, make.patient(), "everything please")
    assert len(tool_messages(state)) == config.MAX_TOOL_CALLS
    assert not state["messages"][-1].tool_calls  # the turn ended


def test_parallel_calls_are_cut_to_the_budget(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    many = AIMessage("", tool_calls=[{"name": "get_my_documents", "args": {}, "id": f"c{i}", "type": "tool_call"}
                                     for i in range(6)])
    fake_llm.agent_script = [many, AIMessage("final")]
    state = ask(graph, thread, make.patient(), "everything at once")
    assert len(tool_messages(state)) == config.MAX_TOOL_CALLS
    assert state["messages"][-1].content == "final"


def test_tool_error_comes_back_as_a_message(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.agent_script = [call("list_my_records", kind="spaceships"), AIMessage("Sorry, I couldn't find that.")]
    state = ask(graph, thread, make.patient(), "my spaceships")
    [result] = tool_messages(state)
    assert result.status == "error"  # invalid kind: reported to the LLM, not a crash
    assert state["messages"][-1].content == "Sorry, I couldn't find that."


# --- memory: earlier turns are remembered, their tool traffic isn't resent ---

def test_second_turn_sees_the_first_without_its_tool_traffic(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    patient = make.patient()
    fake_llm.agent_script = [call("get_my_documents"), AIMessage("You have no documents.")]
    ask(graph, thread, patient, "what documents do I have")
    fake_llm.agent_script = [AIMessage("Still none.")]
    ask(graph, thread, patient, "and now?")
    saw = fake_llm.prompts["agent"][-1]
    texts = [str(m.content) for m in saw]
    assert "what documents do I have" in texts and "You have no documents." in texts and "and now?" in texts
    assert not any(isinstance(m, ToolMessage) or (isinstance(m, AIMessage) and m.tool_calls) for m in saw)


# --- appointment/document lines: only the caller's, tagged, in clinic time ---

def test_lines_only_for_the_caller(db: psycopg.Connection, aja_and_bart) -> None:
    aja, bart = aja_and_bart
    for patient, mine, theirs in ((aja, "Aja", "Bart"), (bart, "Bart", "Aja")):
        appts = " ".join(t for _, t in appointment_lines(db, patient))
        docs = " ".join(t for _, t in document_lines(db, patient))
        assert f"{mine} Upcoming" in appts and f"{mine} Past" in appts
        assert f"{mine.lower()}-card.png" in docs
        assert theirs not in appts and theirs.lower() not in docs
    assert re.search(r"\bE[SD]T\b", appointment_lines(db, aja)[0][1])  # clinic time, converted in code


def test_turn_starts_with_the_patient_message(graph, thread, make: Factory) -> None:
    state = ask(graph, thread, make.patient(), "hi")
    assert isinstance(state["messages"][0], HumanMessage)


def test_prompt_never_turns_a_missing_condition_into_a_no() -> None:
    """The real-model check is evals/run_answers.py --only not-found ("Do I have cancer?")."""
    from app.agent.prompts import AGENT_PROMPT

    rule = " ".join(AGENT_PROMPT.split())
    assert "NEVER say they don't have it" in rule
    assert "can't determine whether they have a condition" in rule and "nurse" in rule


def test_prompt_checks_the_full_list_for_do_i_have() -> None:
    """Real-model check: evals/run_answers.py --only not-found (must call
    list_my_records and never say "the only" conditions)."""
    from app.agent.prompts import AGENT_PROMPT

    rule = " ".join(AGENT_PROMPT.split())
    assert 'check the full list with list_my_records(kind="conditions") before answering' in rule
    assert 'never call search results "the only" conditions' in rule
