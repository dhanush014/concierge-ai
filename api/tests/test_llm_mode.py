"""Fake LLM mode (for E2E): only with APP_ENV=local, loud when on, deterministic."""

import logging

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import llm
from app.agent.fake_llm import FakeChatModel, fake_route
from app.agent.llm import chat_model as real_chat_model  # bound before the autouse fake patches it
from app.agent.prompts import ANSWER_PROMPT
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
    assert isinstance(real_chat_model("answer"), FakeChatModel)
    env(LLM_FAKE=None)
    assert not isinstance(real_chat_model("answer"), FakeChatModel)


# --- the fake's behavior ---

def test_fake_safety_always_ok() -> None:
    reply = FakeChatModel(role="safety").invoke([HumanMessage("I feel dizzy")])
    assert '"ok"' in str(reply.content)


@pytest.mark.parametrize(
    ("text", "route"),
    [
        ("When is my next appointment?", "appointments"),
        ("What documents have I uploaded?", "documents"),
        ("can you reschedule my appointment", "change_appointment"),
        ("hello there", "other"),
    ],
)
def test_fake_router_keywords(text: str, route: str) -> None:
    assert fake_route(text) == route


def test_fake_answer_streams_the_records_back() -> None:
    records = "Upcoming appointments (soonest first):\n- Mon, Oct 12, 2026 at 12:00 PM EDT: Checkup"
    prompt = [SystemMessage(ANSWER_PROMPT.format(records=records)), HumanMessage("when?")]
    pieces = [str(c.content) for c in FakeChatModel(role="answer").stream(prompt)]
    assert len(pieces) > 1
    assert "".join(pieces) == f"Here is what I found.\n{records}"
