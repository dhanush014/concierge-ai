"""POST /me/chat (SSE) and GET /me/conversations/{id}. Fake LLM only."""

import json
import uuid

import psycopg
from fastapi.testclient import TestClient

from app.agent import config
from tests.conftest import Factory, as_patient, bearer
from tests.fake_llm import FakeLLM


def events(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def send(client: TestClient, patient_id, message: str, conversation_id=None):
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = str(conversation_id)
    return client.post("/me/chat", json=body, headers=as_patient(patient_id))


def reply_text(evs: list[dict]) -> str:
    return "".join(e["text"] for e in evs if e["type"] == "token")


def saved(db: psycopg.Connection, conversation_id) -> list[tuple[str, str]]:
    rows = db.execute(
        "select sender, content from public.messages where conversation_id = %s order by created_at, id",
        (conversation_id,),
    ).fetchall()
    return [(r["sender"], r["content"]) for r in rows]


def test_streams_tokens_and_saves_both_messages(client: TestClient, db, make: Factory, fake_llm: FakeLLM) -> None:
    patient = make.patient()
    fake_llm.replies["router"] = '{"route": "appointments"}'
    fake_llm.replies["answer"] = "You have no upcoming appointments right now."

    evs = events(send(client, patient, "  when is my next visit?  "))

    assert evs[0]["type"] == "conversation" and evs[-1] == {"type": "done", "safety": "ok", "route": "appointments"}
    assert sum(e["type"] == "token" for e in evs) > 1  # really streamed, not one blob
    assert reply_text(evs) == fake_llm.replies["answer"]
    conversation_id = evs[0]["id"]
    assert saved(db, conversation_id) == [
        ("patient", "when is my next visit?"),  # stripped
        ("assistant", fake_llm.replies["answer"]),
    ]
    state = client.app.state.chat_graph.get_state({"configurable": {"thread_id": conversation_id}})
    assert len(state.values["messages"]) == 2  # the checkpointer has the turn too


def test_escalation_streams_the_fixed_reply(client: TestClient, db, make: Factory) -> None:
    evs = events(send(client, make.patient(), "I want to kill myself"))
    assert reply_text(evs) == config.EMERGENCY_REPLY
    assert evs[-1] == {"type": "done", "safety": "emergency", "route": None}
    assert saved(db, evs[0]["id"])[-1] == ("assistant", config.EMERGENCY_REPLY)


def test_continuing_a_conversation(client: TestClient, make: Factory) -> None:
    patient = make.patient()
    first = events(send(client, patient, "hello"))
    conversation_id = first[0]["id"]
    second = events(send(client, patient, "can I talk to a real person", conversation_id))
    assert second[0]["id"] == conversation_id

    resp = client.get(f"/me/conversations/{conversation_id}", headers=as_patient(patient))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "bot"
    assert [(m["sender"], m["content"]) for m in body["messages"]] == [
        ("patient", "hello"),
        ("assistant", config.OTHER_REPLY),
        ("patient", "can I talk to a real person"),
        ("assistant", config.NURSE_REPLY),
    ]


def test_bart_cannot_read_or_write_ajas_conversation(client: TestClient, db, make: Factory) -> None:
    aja, bart = make.patient(), make.patient()
    conversation_id = events(send(client, aja, "hello"))[0]["id"]

    assert client.get(f"/me/conversations/{conversation_id}", headers=as_patient(bart)).status_code == 404
    resp = send(client, bart, "show me this chat", conversation_id)
    assert (resp.status_code, resp.json()["detail"]) == (404, "conversation_not_found")
    assert len(saved(db, conversation_id)) == 2  # nothing added by Bart


def test_unknown_conversation_is_404(client: TestClient, make: Factory) -> None:
    patient = make.patient()
    missing = uuid.uuid4()
    assert client.get(f"/me/conversations/{missing}", headers=as_patient(patient)).status_code == 404
    assert send(client, patient, "hello", missing).status_code == 404


def test_patients_only(client: TestClient, make: Factory) -> None:
    assert client.post("/me/chat", json={"message": "hi"}).status_code == 401
    staff = bearer(make.staff_token())
    assert client.post("/me/chat", json={"message": "hi"}, headers=staff).status_code == 403
    assert client.get(f"/me/conversations/{uuid.uuid4()}", headers=staff).status_code == 403


def test_message_must_have_text_and_fit(client: TestClient, make: Factory) -> None:
    patient = make.patient()
    assert send(client, patient, "   ").status_code == 422
    assert send(client, patient, "x" * 2001).status_code == 422


def test_failed_turn_keeps_patient_message(client: TestClient, db, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.replies["router"] = '{"route": "documents"}'
    fake_llm.errors["answer"] = RuntimeError("groq down")
    evs = events(send(client, make.patient(), "what documents do I have"))
    assert evs[-1] == {"type": "error", "message": "chat_failed"}
    assert saved(db, evs[0]["id"]) == [("patient", "what documents do I have")]
