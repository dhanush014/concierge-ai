"""Coverage answers: check_my_coverage and the disclaimer. Fake LLM and embedder; the
contract chunks are the real ones from data/contracts/ (scripts/ingest.py)."""

import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from app.agent import config
from app.agent import record_tools as rt
from app.agent.graph import turn_input, with_disclaimer
from app.rag import embed, rerank
from tests.conftest import Factory, as_patient
from tests.fake_llm import FakeLLM, call
from tests.rag_fixtures import fake_embed


@pytest.fixture(autouse=True)
def fake_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed_texts", fake_embed)
    monkeypatch.setattr(rerank, "score", lambda q, texts: [0.0] * len(texts))


def insure(db: psycopg.Connection, patient: uuid.UUID, payer: str, plan: str | None = None, status: str = "confirmed") -> None:
    db.execute("insert into public.patient_insurance (patient_id, payer, plan_name, status) values (%s, %s, %s, %s)",
               (patient, payer, plan, status))


@pytest.fixture
def patient(db: psycopg.Connection, make: Factory):
    p = make.patient()
    yield p
    db.execute("delete from public.patient_insurance where patient_id = %s", (p,))


# --- the tool ---

def test_no_confirmed_insurance(db, patient) -> None:
    insure(db, patient, "Riverbend Health", status="extracted")  # read but not confirmed: doesn't count
    result = rt.coverage(db, patient, "specialist copay")
    assert result.header.startswith("No confirmed insurance") and "Documents" in result.header and result.lines == []


def test_out_of_network_says_so_without_contract_lines(db, patient) -> None:
    insure(db, patient, "Northstar Benefits", "Northstar Essential EPO")
    result = rt.coverage(db, patient, "specialist copay")
    assert "OUT OF NETWORK" in result.header and config.BILLING_PHONE in result.header and result.lines == []


def test_not_on_file(db, patient) -> None:
    insure(db, patient, "Acme Mutual")
    result = rt.coverage(db, patient, "specialist copay")
    assert "NOT ON FILE" in result.header and result.lines == []


@pytest.mark.parametrize("payer", ["Riverbend Health", "riverbend health plan", "Liberty Senior"])
def test_in_network_reads_only_that_payers_contract(db, patient, payer) -> None:
    insure(db, patient, payer)
    result = rt.coverage(db, patient, "specialist copay")
    canonical = "Riverbend Health" if "riverbend" in payer.lower() else "Liberty Senior Advantage"
    assert "IN NETWORK" in result.header and result.lines
    assert {s.kind for s, _ in result.lines} == {"contract"}
    assert all(s.title.startswith(canonical) for s, _ in result.lines)  # never another payer's plan


def test_latest_confirmed_insurance_wins(db, patient) -> None:
    insure(db, patient, "Northstar Benefits")
    insure(db, patient, "Riverbend Health")
    assert "IN NETWORK" in rt.coverage(db, patient, "copay").header


# --- the disclaimer ---

def test_disclaimer_added_once() -> None:
    assert with_disclaimer("Your copay is $50.").endswith(f"$50.\n\n{config.COVERAGE_DISCLAIMER}")
    already = f"Your copay is $50. {config.COVERAGE_DISCLAIMER}"
    assert with_disclaimer(already) == already
    assert with_disclaimer(already.lower().rstrip(".")) == already.lower().rstrip(".")


@pytest.fixture
def graph(client: TestClient):
    return client.app.state.chat_graph


@pytest.fixture
def thread(db, patient):
    convo = db.execute("insert into public.conversations (patient_id) values (%s) returning id", (patient,)).fetchone()["id"]
    yield {"configurable": {"thread_id": str(convo)}}
    db.execute("delete from public.conversations where id = %s", (convo,))


def test_coverage_answers_always_end_with_the_disclaimer(graph, thread, db, patient, fake_llm: FakeLLM) -> None:
    insure(db, patient, "Riverbend Health")
    fake_llm.agent_script = [call("check_my_coverage", question="specialist copay"), AIMessage("Your specialist copay is $50.")]
    state = graph.invoke(turn_input(patient, "what is my specialist copay"), thread)
    assert state["messages"][-1].content == f"Your specialist copay is $50.\n\n{config.COVERAGE_DISCLAIMER}"


def test_other_answers_get_no_disclaimer(graph, thread, patient, fake_llm: FakeLLM) -> None:
    fake_llm.agent_script = [call("get_my_documents"), AIMessage("You have no documents.")]
    state = graph.invoke(turn_input(patient, "my documents"), thread)
    assert state["messages"][-1].content == "You have no documents."


def test_patient_sees_the_disclaimer_and_contract_sources(
    client: TestClient, db, patient, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rerank, "score", lambda q, texts: [1.0 if "> Copays" in t else 0.0 for t in texts])
    insure(db, patient, "Riverbend Health")
    tag = rt.tag_for("contract:riverbend-health.md#Copays#0")
    fake_llm.agent_script = [call("check_my_coverage", question="specialist copay"),
                             AIMessage(f"Your specialist copay is $50 [{tag}].")]
    resp = client.post("/me/chat", json={"message": "what is my specialist copay"}, headers=as_patient(patient))
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed.endswith(config.COVERAGE_DISCLAIMER)  # streamed too, not only saved
    done = events[-1]
    assert done["tools"] == ["check_my_coverage"]
    assert done["sources"] == [{"tag": tag, "kind": "contract", "title": "Riverbend Health — Riverbend Silver HMO",
                                "section": "Copays", "date": None}]
    convo = client.get(f"/me/conversations/{events[0]['id']}", headers=as_patient(patient)).json()
    assert convo["messages"][-1]["content"].endswith(config.COVERAGE_DISCLAIMER)


def test_tool_schema_hides_the_patient_id() -> None:
    from app.agent.toolkit import make_tools

    tool = next(t for t in make_tools(None) if t.name == "check_my_coverage")
    assert list(tool.tool_call_schema.model_json_schema()["properties"]) == ["question"]


def test_coverage_tool_result_is_a_tool_message(graph, thread, db, patient, fake_llm: FakeLLM) -> None:
    fake_llm.agent_script = [call("check_my_coverage", question="copay"), AIMessage("Please upload your card.")]
    state = graph.invoke(turn_input(patient, "what's my copay"), thread)
    [result] = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert result.content.startswith("No confirmed insurance") and result.artifact == []
