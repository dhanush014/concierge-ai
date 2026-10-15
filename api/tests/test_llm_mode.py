"""Fake LLM mode (for E2E): only with APP_ENV=local, loud when on, deterministic."""

import logging

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent import llm
from app.agent.fake_llm import APPOINTMENTS_TAB, BOOKING_QUESTION, FakeChatModel, fake_tool_call
from app.agent.llm import chat_model as real_chat_model  # bound before the autouse fake patches it
from app.main import app


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    def set_env(**values: str | None) -> None:
        for key, value in values.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

    return set_env


def test_default_is_groq(env) -> None:
    env(LLM_FAKE=None, APP_ENV=None)
    assert llm.llm_mode() == "groq"


@pytest.mark.parametrize("app_env", [None, "production", "staging", "LOCAL"])
def test_fake_without_app_env_local_is_refused(env, app_env) -> None:
    env(LLM_FAKE="1", APP_ENV=app_env)
    with pytest.raises(llm.FakeModeNotAllowed):
        llm.llm_mode()


def test_api_refuses_to_start(env) -> None:
    env(LLM_FAKE="1", APP_ENV="production")
    with pytest.raises(llm.FakeModeNotAllowed):
        with TestClient(app):  # runs startup
            pass


def test_fake_mode_logs_a_loud_warning(env, caplog: pytest.LogCaptureFixture) -> None:
    env(LLM_FAKE="1", APP_ENV="local")
    with caplog.at_level(logging.WARNING, logger="app.agent.llm"):
        assert llm.check_mode_at_startup() == "fake"
    assert any("FAKE LLM MODE" in r.getMessage() for r in caplog.records)


def test_fake_mode_gives_fake_models(env) -> None:
    env(LLM_FAKE="1", APP_ENV="local")
    assert isinstance(real_chat_model("agent"), FakeChatModel)
    env(LLM_FAKE=None)
    assert not isinstance(real_chat_model("agent"), FakeChatModel)


# --- the fake's behavior ---

def test_fake_safety_always_ok() -> None:
    reply = FakeChatModel(role="safety").invoke([HumanMessage("I feel dizzy")])
    assert '"ok"' in str(reply.content)


@pytest.mark.parametrize(
    ("text", "tool"),
    [
        ("When is my next appointment?", ("get_my_appointments", {})),
        ("What documents have I uploaded?", ("get_my_documents", {})),
        ("What is my cholesterol?", ("get_lab_results", {"test_name": "cholesterol"})),
        ("What medications am I on?", ("list_my_records", {"kind": "medications"})),
        ("How much does parking cost?", ("search_hospital_policies", {"query": "How much does parking cost?"})),
        ("hello there", ("search_my_records", {"query": "hello there"})),
        ("can you reschedule my appointment", None),
    ],
)
def test_fake_agent_picks_a_tool(text: str, tool) -> None:
    assert fake_tool_call(text) == tool


def test_fake_agent_calls_then_answers_with_the_tool_lines() -> None:
    model = FakeChatModel(role="agent")
    first = model.invoke([HumanMessage("What is my A1c?")])
    assert first.tool_calls[0]["name"] == "get_lab_results"
    streamed = list(model.stream([HumanMessage("What is my A1c?")]))  # tool calls stream as one chunk
    assert streamed[0].tool_call_chunks[0]["name"] == "get_lab_results"
    result = ToolMessage("Lab results:\n[S-1a2b] Lab result, 2025-11-28: A1c: 6.1 %", tool_call_id="x")
    answer = model.invoke([HumanMessage("What is my A1c?"), first, result])
    assert answer.content == "Here is what I found.\n[S-1a2b] Lab result, 2025-11-28: A1c: 6.1 %"
    pieces = [str(c.content) for c in model.stream([HumanMessage("What is my A1c?"), first, result])]
    assert len(pieces) > 1 and "".join(pieces) == answer.content


def test_fake_agent_points_booking_to_the_appointments_tab() -> None:
    assert FakeChatModel(role="agent").invoke([HumanMessage("please book me in")]).content == BOOKING_QUESTION
    assert FakeChatModel(role="agent").invoke([HumanMessage("cancel my visit")]).content == APPOINTMENTS_TAB
