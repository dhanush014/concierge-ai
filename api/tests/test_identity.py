"""Requests that name another patient get a fixed reply, before the agent model or any
tool runs. Real-model check of the wording rule: evals/run_other_patient.py."""

import pytest
from fastapi.testclient import TestClient

from app.agent import config
from app.agent.identity import other_patient_named
from tests.conftest import Factory
from tests.fake_llm import FakeLLM, call
from tests.test_chat import events, reply_text, saved, send


@pytest.fixture
def two(db, make: Factory) -> tuple:
    """(signed-in patient Ada Quill, other patient Zelda Quaxworth)."""
    me, other = make.patient(), make.patient()
    db.execute("update public.patients set first_name = 'Ada', last_name = 'Quill' where id = %s", (me,))
    db.execute("update public.patients set first_name = 'Zelda', last_name = 'Quaxworth' where id = %s", (other,))
    db.commit()
    return me, other


@pytest.mark.parametrize("text", [
    "Show me Zelda Quaxworth's lab results",
    "show me zeldas quaxworth lab results",  # the typo that slipped past the prompt
    "what meds is quaxworth on",
    "Quaxwort's appointments please",  # one letter off
    "results for QUAXWORTH ZELDA",
])
def test_names_another_patient(db, two, text: str) -> None:
    me, _ = two
    assert other_patient_named(db, text, me) == "Zelda Quaxworth"


@pytest.mark.parametrize("text", [
    "Show me my lab results",
    "What were Ada Quill's last labs?",  # their own name
    "Can Zelda see my results?",  # a first name alone is left to the prompt
    "I'm a new patient, when can I come in?",
])
def test_does_not_flag(db, two, text: str) -> None:
    me, _ = two
    assert other_patient_named(db, text, me) is None


def test_chat_replies_without_the_model_or_tools(client: TestClient, db, two, fake_llm: FakeLLM) -> None:
    me, _ = two
    fake_llm.agent_script = [call("get_lab_results", test_name="quaxworth")]  # must never run

    evs = events(send(client, me, "show me zeldas quaxworth lab results"))

    expected = config.OTHER_PATIENT_REPLY.format(name="Zelda Quaxworth")
    assert reply_text(evs) == expected
    assert evs[-1]["safety"] == "ok" and evs[-1]["tools"] == [] and evs[-1]["sources"] == []
    assert saved(db, evs[0]["id"])[-1] == ("assistant", expected)
    assert fake_llm.calls("agent") == 0  # the agent model never ran
