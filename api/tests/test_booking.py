"""Chat-assisted booking: find_open_times finds the slot, the reply opens the prefilled
booking page, and nothing is booked until the patient confirms there."""

import json
from datetime import datetime, time, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent import booking
from app.agent.config import CLINIC_TZ
from tests.conftest import Factory, as_patient
from tests.fake_llm import FakeLLM, call


def slot_at(db, doctor, start: datetime, visit_type: str = "Follow-up"):
    return db.execute("insert into public.slots (doctor_id, start_at, end_at, visit_type) values (%s, %s, %s, %s)"
                      " returning id", (doctor, start, start + timedelta(minutes=30), visit_type)).fetchone()["id"]


@pytest.fixture
def world(db, make: Factory):
    """Two test doctors; Dr. Quorra (cardiology) is open at 10:00 and 12:00 in 3 days."""
    cardio, derm = make.doctor("Cardiology"), make.doctor("Dermatology")
    db.execute("update public.doctors set name = 'Dr. Zed Quorra' where id = %s", (cardio,))
    db.execute("update public.doctors set name = 'Dr. Ines Vantablack' where id = %s", (derm,))
    day = datetime.now(CLINIC_TZ).date() + timedelta(days=3)
    start = datetime.combine(day, time(10), CLINIC_TZ)
    first, later = slot_at(db, cardio, start), slot_at(db, cardio, start + timedelta(hours=2))
    return {"cardio": cardio, "derm": derm, "first": first, "later": later, "start": start}


def test_exact_match_proposes_that_slot(db, world) -> None:
    text, artifact = booking.find_open_times(db, world["start"].date(), time(10),
                                             "Dr. Quorra")
    assert "exactly as asked" in text and "Confirm booking" in text
    [proposal] = artifact
    assert proposal["slot_id"] == str(world["first"]) and proposal["doctor_id"] == str(world["cardio"])
    action = booking.Proposal(**proposal).action()
    query = parse_qs(urlparse(action["href"]).query)
    assert action["label"] == "Review and book" and urlparse(action["href"]).path == "/portal/appointments/book"
    assert query == {"doctor": [str(world["cardio"])], "type": ["Follow-up"], "slot": [str(world["first"])]}


def test_specialty_words_match(db, world) -> None:
    assert booking.doctor_matches("a cardiologist", "Dr. Zed Quorra", "Cardiology")
    assert not booking.doctor_matches("dermatologist", "Dr. Zed Quorra", "Cardiology")


def test_time_not_open_lists_that_day_closest_first(db, world) -> None:
    asked = time(11, 45)  # nearer the 12:00 slot
    text, artifact = booking.find_open_times(db, world["start"].date(), asked, "quorra")
    assert artifact == [] and text.startswith("Not open at")
    lines = text.splitlines()[1:]
    assert len(lines) == 2 and lines[0].startswith(booking.clinic_time(world["start"] + timedelta(hours=2))[:10])


def test_no_time_lists_the_day(db, world) -> None:
    text, artifact = booking.find_open_times(db, world["start"].date(), None, "quorra")
    assert artifact == [] and text.startswith("Open times on") and len(text.splitlines()) == 3


def test_empty_day_lists_the_next_open_times(db, world) -> None:
    day_before = world["start"].date() - timedelta(days=1)
    text, artifact = booking.find_open_times(db, day_before, None, "quorra")
    assert artifact == [] and "next open times" in text and "Follow-up with Dr. Zed Quorra" in text


def test_unknown_doctor_lists_the_doctors(db, world) -> None:
    text, artifact = booking.find_open_times(db, world["start"].date(), None, "Dr. Nobodyhere")
    assert artifact == [] and "No doctor matches" in text and "Dr. Ines Vantablack (Dermatology)" in text


def test_past_day(db, world) -> None:
    text, _ = booking.find_open_times(db, datetime.now(CLINIC_TZ).date() - timedelta(days=2), None, None)
    assert "has passed" in text


def test_booked_slots_are_not_offered(db, world, make: Factory) -> None:
    make.book_directly(make.patient(), world["first"])
    text, artifact = booking.find_open_times(db, world["start"].date(), time(10),
                                             "quorra")
    assert artifact == [] and text.startswith("Not open at")


def test_chat_reply_carries_the_action_and_books_nothing(client: TestClient, db, world, make: Factory,
                                                         fake_llm: FakeLLM) -> None:
    patient = make.patient()
    start = world["start"]
    fake_llm.agent_script = [
        call("find_open_times", date=start.date().isoformat(), time="10:00", doctor="Quorra"),
        AIMessage("That time is open. The booking page is opening so you can confirm."),
    ]
    resp = client.post("/me/chat", json={"message": "book Dr. Quorra then"}, headers=as_patient(patient))
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    done = events[-1]
    assert done["tools"] == ["find_open_times"] and done["sources"] == []
    assert done["action"]["label"] == "Review and book" and str(world["first"]) in done["action"]["href"]

    convo = client.get(f"/me/conversations/{events[0]['id']}", headers=as_patient(patient)).json()
    assert convo["messages"][-1]["action"] == done["action"]  # still there after a reload
    booked = db.execute("select count(*) n from public.appointments where slot_id = %s", (world["first"],)).fetchone()
    assert booked["n"] == 0  # the patient books on the page, not the chat


def test_no_action_without_an_exact_match(client: TestClient, world, make: Factory, fake_llm: FakeLLM) -> None:
    fake_llm.agent_script = [call("find_open_times", date=world["start"].date().isoformat(), doctor="Quorra"),
                             AIMessage("Here are the open times.")]
    resp = client.post("/me/chat", json={"message": "book Dr. Quorra"}, headers=as_patient(make.patient()))
    done = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")][-1]
    assert done["action"] is None


def test_bad_date_is_explained(make: Factory) -> None:
    from app.agent.toolkit import make_tools

    tool = next(t for t in make_tools(None) if t.name == "find_open_times")
    assert "YYYY-MM-DD" in tool.func(date="next tuesday")[0]


def test_prompt_has_todays_date() -> None:
    from app.agent.graph import agent_prompt

    assert datetime.now(CLINIC_TZ).strftime("%Y-%m-%d") in agent_prompt()

