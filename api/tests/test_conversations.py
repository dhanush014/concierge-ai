"""GET /me/conversations/latest, message kinds, and the delete cleanup trigger."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.conftest import Factory, as_patient, bearer
from tests.fake_llm import FakeLLM

CHECKPOINT_TABLES_SQL = (
    "select table_name from information_schema.columns"
    " where table_schema = 'langgraph' and column_name = 'thread_id'"
)


def send(client: TestClient, patient_id, message: str, conversation_id=None) -> str:
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    resp = client.post("/me/chat", json=body, headers=as_patient(patient_id))
    assert resp.status_code == 200
    first = json.loads(resp.text.splitlines()[0][6:])
    return first["id"]


def latest(client: TestClient, patient_id):
    resp = client.get("/me/conversations/latest", headers=as_patient(patient_id))
    assert resp.status_code == 200
    return resp.json()


# --- latest ---

def test_latest_is_null_without_conversations(client: TestClient, make: Factory) -> None:
    assert latest(client, make.patient()) is None


def test_latest_is_the_newest_with_its_messages(client: TestClient, make: Factory) -> None:
    patient = make.patient()
    send(client, patient, "first chat")
    newest = send(client, patient, "second chat")
    body = latest(client, patient)
    assert body["id"] == newest
    assert [m["content"] for m in body["messages"] if m["sender"] == "patient"] == ["second chat"]


def test_latest_never_returns_another_patients(client: TestClient, make: Factory) -> None:
    aja, bart = make.patient(), make.patient()
    send(client, aja, "hello")
    assert latest(client, bart) is None


def test_latest_is_patients_only(client: TestClient, make: Factory) -> None:
    assert client.get("/me/conversations/latest").status_code == 401
    staff = bearer(make.staff_token())
    assert client.get("/me/conversations/latest", headers=staff).status_code == 403


# --- message kind: how the UI shows each reply, kept across reloads ---

@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("hello", "text"),
        ("I can't breathe", "emergency"),
        ("I feel dizzy", "handoff"),
        ("can I talk to a real person", "handoff"),
    ],
)
def test_reply_kind_is_saved(client: TestClient, make: Factory, message: str, kind: str) -> None:
    patient = make.patient()
    conversation_id = send(client, patient, message)
    body = client.get(f"/me/conversations/{conversation_id}", headers=as_patient(patient)).json()
    assert [(m["sender"], m["kind"]) for m in body["messages"]] == [("patient", "text"), ("assistant", kind)]


# --- deleting a conversation deletes all of its LangGraph state ---

def test_delete_clears_every_checkpoint_table(
    client: TestClient, db: psycopg.Connection, make: Factory, fake_llm: FakeLLM
) -> None:
    patient = make.patient()
    fake_llm.replies["router"] = '{"route": "appointments"}'  # runs every node type, incl. writes
    conversation_id = send(client, patient, "when is my next visit")
    send(client, patient, "and after that?", conversation_id)

    tables = [r["table_name"] for r in db.execute(CHECKPOINT_TABLES_SQL).fetchall()]
    assert sorted(tables) == ["checkpoint_blobs", "checkpoint_writes", "checkpoints"]

    def rows(table: str) -> int:
        return db.execute(
            f"select count(*) as n from langgraph.{table} where thread_id = %s", (conversation_id,)
        ).fetchone()["n"]

    assert all(rows(t) > 0 for t in tables)  # the turns really wrote to every table

    db.execute("delete from public.conversations where id = %s", (conversation_id,))
    assert {t: rows(t) for t in tables} == {t: 0 for t in tables}
    assert db.execute(
        "select count(*) as n from public.messages where conversation_id = %s", (conversation_id,)
    ).fetchone()["n"] == 0
