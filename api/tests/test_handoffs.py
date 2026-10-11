"""Handoff to staff: graph pause/resume, patient chat during handoff, staff endpoints."""

import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import handoffs
from app.agent import config
from tests.conftest import Factory, as_patient, bearer
from tests.fake_llm import FakeLLM


def events(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def say(client: TestClient, patient, text: str, conversation_id=None) -> list[dict]:
    body = {"message": text, **({"conversation_id": str(conversation_id)} if conversation_id else {})}
    return events(client.post("/me/chat", json=body, headers=as_patient(patient)))


def handoff_rows(db: psycopg.Connection, conversation_id) -> list[dict]:
    return db.execute(
        "select * from public.handoffs where conversation_id = %s order by created_at", (conversation_id,)
    ).fetchall()


def messages(db: psycopg.Connection, conversation_id) -> list[tuple[str, str, str]]:
    rows = db.execute(
        "select sender, kind, content from public.messages where conversation_id = %s order by created_at, id",
        (conversation_id,),
    ).fetchall()
    return [(r["sender"], r["kind"], r["content"]) for r in rows]


def paused(client: TestClient, conversation_id) -> bool:
    state = client.app.state.chat_graph.get_state({"configurable": {"thread_id": str(conversation_id)}})
    return bool(state.next)


@pytest.fixture
def ticket(client: TestClient, db, make: Factory) -> dict:
    """Aja asked for a person: an open handoff, plus a staff member (Kim) to work it."""
    aja = make.patient()
    conversation_id = say(client, aja, "can I talk to a real person")[0]["id"]
    [row] = handoff_rows(db, conversation_id)
    return {"aja": aja, "conversation_id": conversation_id, "id": row["id"], "kim": bearer(make.staff_token())}


def staff_post(client: TestClient, ticket: dict, action: str, headers=None, **body):
    return client.post(f"/staff/handoffs/{ticket['id']}/{action}", json=body or None, headers=headers or ticket["kim"])


# --- the graph creates the handoff and pauses ---

def test_asking_for_a_person_opens_a_handoff_and_pauses(client: TestClient, db, make: Factory, fake_llm: FakeLLM) -> None:
    aja = make.patient()
    evs = say(client, aja, "can I talk to a real person")
    conversation_id = evs[0]["id"]

    assert evs[-1]["status"] == "handoff" and evs[-1]["kind"] == "handoff"
    [row] = handoff_rows(db, conversation_id)
    assert (row["reason"], row["status"], row["summary"]) == ("wants_human", "open", fake_llm.replies["summary"])
    assert row["trace_id"]  # the LangSmith run id of this turn
    assert db.execute("select status from public.conversations where id = %s", (conversation_id,)).fetchone()["status"] == "handoff"
    assert paused(client, conversation_id)


@pytest.mark.parametrize(("text", "reason"), [("I feel dizzy", "clinical"), ("I want to kill myself", "emergency")])
def test_each_escalation_reason(client: TestClient, db, make: Factory, text: str, reason: str) -> None:
    conversation_id = say(client, make.patient(), text)[0]["id"]
    assert handoff_rows(db, conversation_id)[0]["reason"] == reason


def test_emergency_shows_911_before_the_handoff(client: TestClient, db, make: Factory) -> None:
    evs = say(client, make.patient(), "I can't breathe")
    kinds = [e["type"] for e in evs]
    assert kinds.index("token") < kinds.index("notice")  # 911 text first, then "nurse notified"
    assert messages(db, evs[0]["id"])[1:] == [
        ("assistant", "emergency", config.EMERGENCY_REPLY),
        ("assistant", "notice", config.NURSE_NOTIFIED_NOTICE),
    ]


def test_summary_failure_still_hands_off(client: TestClient, db, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.errors["summary"] = RuntimeError("groq down")
    conversation_id = say(client, make.patient(), "can I talk to a real person")[0]["id"]
    assert handoff_rows(db, conversation_id)[0]["summary"] == 'Patient wrote: "can I talk to a real person"'


# --- while in handoff the agent is silent (except emergencies) ---

def test_patient_messages_during_handoff_get_no_reply(client: TestClient, db, ticket: dict, fake_llm: FakeLLM) -> None:
    evs = say(client, ticket["aja"], "are you there?", ticket["conversation_id"])
    assert [e["type"] for e in evs] == ["conversation", "done"]
    assert evs[-1]["status"] == "handoff"
    assert messages(db, ticket["conversation_id"])[-1] == ("patient", "text", "are you there?")
    assert fake_llm.calls("router") == 0 and len(handoff_rows(db, ticket["conversation_id"])) == 1


def test_emergency_during_handoff_still_gets_911_and_flags_ticket(client: TestClient, db, ticket: dict) -> None:
    evs = say(client, ticket["aja"], "my face is drooping", ticket["conversation_id"])
    assert "".join(e["text"] for e in evs if e["type"] == "token") == config.EMERGENCY_REPLY
    [row] = handoff_rows(db, ticket["conversation_id"])
    assert row["reason"] == "emergency"


# --- never two live handoffs for one conversation ---

def test_no_second_live_handoff(db: psycopg.Connection, ticket: dict) -> None:
    again, created = handoffs.open_handoff(db, ticket["conversation_id"], "clinical", "again", None)
    assert (again["id"], created) == (ticket["id"], False)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into public.handoffs (conversation_id, reason, summary) values (%s, 'clinical', 'x')",
            (ticket["conversation_id"],),
        )


# --- staff endpoints and role checks ---

def test_staff_only(client: TestClient, ticket: dict) -> None:
    for method, path in [
        ("get", "/staff/handoffs"),
        ("get", f"/staff/handoffs/{ticket['id']}"),
        ("post", f"/staff/handoffs/{ticket['id']}/join"),
        ("post", f"/staff/handoffs/{ticket['id']}/messages"),
        ("post", f"/staff/handoffs/{ticket['id']}/close"),
    ]:
        assert getattr(client, method)(path).status_code == 401
        assert getattr(client, method)(path, headers=as_patient(ticket["aja"])).status_code == 403


def test_list_and_filter(client: TestClient, ticket: dict) -> None:
    def ids(status=None):
        resp = client.get("/staff/handoffs", params={"status": status} if status else None, headers=ticket["kim"])
        assert resp.status_code == 200
        return [h["id"] for h in resp.json()]

    assert str(ticket["id"]) in ids() and str(ticket["id"]) in ids("open")
    assert str(ticket["id"]) not in ids("active") + ids("closed")


def test_detail_has_summary_transcript_and_no_trace_link_without_langsmith(client: TestClient, ticket: dict) -> None:
    body = client.get(f"/staff/handoffs/{ticket['id']}", headers=ticket["kim"]).json()
    assert body["reason"] == "wants_human" and body["summary"]
    assert body["patient_name"] == "Test Patient0"
    assert [m["sender"] for m in body["messages"]][:2] == ["patient", "assistant"]
    assert body["trace_url"] is None


def test_unknown_handoff_is_404(client: TestClient, make: Factory) -> None:
    staff = bearer(make.staff_token())
    assert client.get(f"/staff/handoffs/{uuid.uuid4()}", headers=staff).status_code == 404
    assert client.post(f"/staff/handoffs/{uuid.uuid4()}/join", headers=staff).status_code == 404


def test_join_once_first_come_first_served(client: TestClient, db, ticket: dict, make: Factory) -> None:
    resp = staff_post(client, ticket, "join")
    assert resp.status_code == 200
    assert (resp.json()["status"], resp.json()["staff_name"]) == ("active", "Test staff")
    assert staff_post(client, ticket, "join").status_code == 200  # again: no change
    joined = [m for m in messages(db, ticket["conversation_id"]) if m[1] == "notice" and "joined" in m[2]]
    assert joined == [("staff", "notice", "Test staff joined the chat.")]

    other = bearer(make.staff_token())
    assert (staff_post(client, ticket, "join", other).json()["detail"]) == "handoff_taken"


def test_reply_needs_join_and_reaches_the_patient(client: TestClient, ticket: dict, make: Factory) -> None:
    resp = staff_post(client, ticket, "messages", content="Hi, how can I help?")
    assert (resp.status_code, resp.json()["detail"]) == (409, "not_joined")
    staff_post(client, ticket, "join")
    assert staff_post(client, ticket, "messages", content="   ").status_code == 422
    resp = staff_post(client, ticket, "messages", content="Hi, how can I help?")
    assert resp.status_code == 201 and resp.json()["staff_name"] == "Test staff"
    assert staff_post(client, ticket, "messages", bearer(make.staff_token()), content="me too").status_code == 409

    convo = client.get(f"/me/conversations/{ticket['conversation_id']}", headers=as_patient(ticket["aja"])).json()
    staff_said = [(m["content"], m["staff_name"]) for m in convo["messages"] if m["sender"] == "staff" and m["kind"] == "text"]
    assert staff_said == [("Hi, how can I help?", "Test staff")]


def test_close_resumes_the_assistant(client: TestClient, db, ticket: dict, fake_llm: FakeLLM) -> None:
    staff_post(client, ticket, "join")
    say(client, ticket["aja"], "my appointment question", ticket["conversation_id"])
    staff_post(client, ticket, "messages", content="Your visit is on Monday.")
    assert staff_post(client, ticket, "close", bearer("not-a-token")).status_code == 401

    resp = staff_post(client, ticket, "close")
    assert resp.status_code == 200 and resp.json()["status"] == "closed" and resp.json()["closed_at"]
    cid = ticket["conversation_id"]
    assert db.execute("select status from public.conversations where id = %s", (cid,)).fetchone()["status"] == "bot"
    assert messages(db, cid)[-1] == ("assistant", "notice", config.ASSISTANT_BACK_NOTICE)
    assert not paused(client, cid)

    # The graph remembers the handoff, and the assistant answers again.
    fake_llm.replies["router"] = '{"route": "appointments"}'
    evs = say(client, ticket["aja"], "when is my next visit", cid)
    assert evs[-1]["status"] == "bot" and evs[-1]["route"] == "appointments"
    router_saw = " ".join(str(m.content) for m in fake_llm.prompts["router"][-1])
    assert "my appointment question" in router_saw and "Test staff: Your visit is on Monday." in router_saw

    assert staff_post(client, ticket, "close").json()["detail"] == "handoff_closed"
    assert staff_post(client, ticket, "join").json()["detail"] == "handoff_closed"


def test_close_needs_the_staff_who_joined(client: TestClient, ticket: dict, make: Factory) -> None:
    assert staff_post(client, ticket, "close").json()["detail"] == "not_joined"
    staff_post(client, ticket, "join")
    assert staff_post(client, ticket, "close", bearer(make.staff_token())).json()["detail"] == "not_joined"


def test_a_new_handoff_after_close(client: TestClient, db, ticket: dict) -> None:
    staff_post(client, ticket, "join")
    staff_post(client, ticket, "close")
    say(client, ticket["aja"], "can I talk to a real person", ticket["conversation_id"])
    assert [r["status"] for r in handoff_rows(db, ticket["conversation_id"])] == ["closed", "open"]
