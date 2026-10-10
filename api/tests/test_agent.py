"""The LangGraph agent: routing, fixed replies, tools, memory. Fake LLM only."""

import json
import re
import uuid
from collections.abc import Iterator
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent import config
from app.agent.graph import turn_input
from app.agent.tools import get_my_appointments, get_my_documents
from tests.conftest import Factory
from tests.fake_llm import FakeLLM


@pytest.fixture
def graph(client: TestClient):
    return client.app.state.chat_graph


@pytest.fixture
def thread(graph) -> Iterator[dict]:
    """A throwaway checkpointer thread, deleted afterwards."""
    thread_id = str(uuid.uuid4())
    yield {"configurable": {"thread_id": thread_id}}
    graph.checkpointer.delete_thread(thread_id)


def route_to(route: str) -> str:
    return json.dumps({"route": route})


def ask(graph, thread: dict, patient_id: uuid.UUID, text: str) -> dict:
    return graph.invoke(turn_input(patient_id, text), thread)


# --- safety categories end the turn with a fixed reply, router never runs ---

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
    assert fake_llm.calls("router") == fake_llm.calls("answer") == 0


# --- each route ---

@pytest.mark.parametrize(
    ("route", "reply"),
    [("change_appointment", config.CHANGE_APPOINTMENT_REPLY), ("other", config.OTHER_REPLY)],
)
def test_reply_routes_use_fixed_text(graph, thread, make: Factory, fake_llm: FakeLLM, route, reply) -> None:
    fake_llm.replies["router"] = route_to(route)
    state = ask(graph, thread, make.patient(), "hello")
    assert (state["safety"], state["route"]) == ("ok", route)
    assert state["messages"][-1].content == reply
    assert fake_llm.calls("answer") == 0


@pytest.mark.parametrize("route", ["appointments", "documents"])
def test_tool_routes_answer_from_records(graph, thread, make: Factory, fake_llm: FakeLLM, route) -> None:
    fake_llm.replies["router"] = route_to(route)
    state = ask(graph, thread, make.patient(), "what do you have for me")
    assert state["route"] == route
    assert state["messages"][-1].content == fake_llm.replies["answer"]
    system_prompt = fake_llm.prompts["answer"][0][0].content
    assert state["records"] in system_prompt


@pytest.mark.parametrize("router_reply", ['{"route": "delete_everything"}', "not json"])
def test_unknown_route_falls_back_to_other(graph, thread, make: Factory, fake_llm: FakeLLM, router_reply) -> None:
    fake_llm.replies["router"] = router_reply
    assert ask(graph, thread, make.patient(), "hello")["route"] == "other"


def test_router_outage_falls_back_to_other(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.errors["router"] = RuntimeError("groq down")
    state = ask(graph, thread, make.patient(), "hello")
    assert (state["route"], state["messages"][-1].content) == ("other", config.OTHER_REPLY)


# --- tools only ever see the caller's data ---

@pytest.fixture
def two_patients(make: Factory) -> tuple[uuid.UUID, uuid.UUID]:
    """Aja and Bart, each with one upcoming appointment, one past one, one document."""
    patients = []
    for name in ("Aja", "Bart"):
        patient = make.patient()
        doctor = make.doctor(specialty=f"{name} Specialty")
        make.book_directly(patient, make.slot(doctor, timedelta(days=2), visit_type=f"{name} Upcoming"))
        make.book_directly(patient, make.slot(doctor, timedelta(days=-2), visit_type=f"{name} Past"))
        make.document_row(patient, f"{name.lower()}-card.png")
        patients.append(patient)
    return patients[0], patients[1]


def test_tools_return_only_the_callers_data(db: psycopg.Connection, two_patients) -> None:
    aja, bart = two_patients
    for patient, mine, theirs in ((aja, "Aja", "Bart"), (bart, "Bart", "Aja")):
        appts = get_my_appointments(db, patient)
        docs = get_my_documents(db, patient)
        assert f"{mine} Upcoming" in appts and f"{mine} Past" in appts
        assert f"{mine.lower()}-card.png" in docs
        assert theirs not in appts and theirs.lower() not in docs


def test_answer_model_only_sees_the_callers_records(graph, thread, two_patients, fake_llm: FakeLLM) -> None:
    aja, _ = two_patients
    fake_llm.replies["router"] = route_to("appointments")
    ask(graph, thread, aja, "when is my next visit")
    prompt_text = " ".join(str(m.content) for m in fake_llm.prompts["answer"][0])
    assert "Aja Upcoming" in prompt_text and "Bart" not in prompt_text


def test_tools_show_clinic_time(db: psycopg.Connection, two_patients) -> None:
    """Times are converted in code (America/New_York), not left to the LLM."""
    assert re.search(r"\bE[SD]T\b", get_my_appointments(db, two_patients[0]))


# --- memory: the checkpointer keeps the thread ---

def test_second_turn_sees_the_first(graph, thread, make: Factory, fake_llm: FakeLLM) -> None:
    patient = make.patient()
    fake_llm.replies["router"] = route_to("appointments")
    ask(graph, thread, patient, "when is my next visit")
    state = ask(graph, thread, patient, "and the one after that?")
    assert [m.type for m in state["messages"]] == ["human", "ai", "human", "ai"]
    router_saw = [m.content for m in fake_llm.prompts["router"][1]]
    assert "when is my next visit" in router_saw and "and the one after that?" in router_saw
