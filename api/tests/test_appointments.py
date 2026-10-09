import logging
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi.testclient import TestClient

from app.db import get_conn
from app.main import app
from tests.conftest import Factory, as_patient

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


def slot_ids(client: TestClient, **params: str) -> set[str]:
    resp = client.get("/slots", params=params)
    assert resp.status_code == 200
    return {s["id"] for s in resp.json()}


def book(client: TestClient, patient_id, slot_id):
    return client.post("/appointments", json={"slot_id": str(slot_id)}, headers=as_patient(patient_id))


# --- doctors and slots -------------------------------------------------------


def test_doctors_lists_visit_types(client: TestClient, make: Factory) -> None:
    doc = make.doctor()
    make.slot(doc, DAY, "Checkup")
    make.slot(doc, 2 * DAY, "Follow-up")

    resp = client.get("/doctors")

    assert resp.status_code == 200
    mine = next(d for d in resp.json() if d["id"] == str(doc))
    assert mine["visit_types"] == ["Checkup", "Follow-up"]


def test_slots_never_returns_past_slots(client: TestClient, make: Factory) -> None:
    doc = make.doctor()
    past = make.slot(doc, -HOUR)
    future = make.slot(doc, HOUR)
    far_back = (datetime.now(timezone.utc) - 7 * DAY).isoformat()

    ids = slot_ids(client, doctor_id=str(doc), date_from=far_back)

    assert ids == {str(future)}
    assert str(past) not in ids


def test_slots_default_window_is_now_to_14_days(client: TestClient, make: Factory) -> None:
    doc = make.doctor()
    make.slot(doc, -HOUR)
    inside = {make.slot(doc, HOUR), make.slot(doc, 13 * DAY)}
    make.slot(doc, 15 * DAY)

    assert slot_ids(client, doctor_id=str(doc)) == {str(s) for s in inside}


def test_slots_filters_by_visit_type(client: TestClient, make: Factory) -> None:
    doc = make.doctor()
    checkup = make.slot(doc, HOUR, "Checkup")
    make.slot(doc, 2 * HOUR, "Follow-up")

    assert slot_ids(client, doctor_id=str(doc), visit_type="Checkup") == {str(checkup)}


def test_slots_returns_at_most_200(client: TestClient, make: Factory, db: psycopg.Connection) -> None:
    doc = make.doctor()
    db.execute(
        "insert into public.slots (doctor_id, start_at, end_at, visit_type)"
        " select %s, now() + i * interval '30 min', now() + (i + 1) * interval '30 min', 'Checkup'"
        " from generate_series(1, 205) as i",
        (doc,),
    )

    resp = client.get("/slots", params={"doctor_id": str(doc)})

    assert resp.status_code == 200
    assert len(resp.json()) == 200


# --- book, cancel, reschedule -----------------------------------------------


def test_book_removes_slot_from_open_slots(client: TestClient, make: Factory) -> None:
    doc, pat = make.doctor(), make.patient()
    slot = make.slot(doc, DAY)

    resp = book(client, pat, slot)

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "booked"
    assert body["slot_id"] == str(slot)
    assert body["start_at"].endswith("Z")  # UTC
    assert str(slot) not in slot_ids(client, doctor_id=str(doc))


def test_cancel_reopens_slot(client: TestClient, make: Factory) -> None:
    doc, pat = make.doctor(), make.patient()
    slot = make.slot(doc, DAY)
    appt = book(client, pat, slot).json()["id"]

    resp = client.post(f"/appointments/{appt}/cancel", headers=as_patient(pat))

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert str(slot) in slot_ids(client, doctor_id=str(doc))


def test_reschedule_moves_to_new_slot(client: TestClient, make: Factory) -> None:
    doc, pat = make.doctor(), make.patient()
    old_slot, new_slot = make.slot(doc, DAY), make.slot(doc, 2 * DAY)
    old = book(client, pat, old_slot).json()["id"]

    resp = client.post(
        f"/appointments/{old}/reschedule",
        json={"new_slot_id": str(new_slot)},
        headers=as_patient(pat),
    )

    assert resp.status_code == 201
    new = resp.json()
    assert new["id"] != old
    assert new["slot_id"] == str(new_slot)
    open_ids = slot_ids(client, doctor_id=str(doc))
    assert str(old_slot) in open_ids and str(new_slot) not in open_ids
    upcoming = client.get("/me/appointments", headers=as_patient(pat)).json()
    assert [a["id"] for a in upcoming] == [new["id"]]


def test_my_appointments_splits_upcoming_and_past(client: TestClient, make: Factory) -> None:
    doc, pat = make.doctor(), make.patient()
    past = make.book_directly(pat, make.slot(doc, -DAY))
    soon = book(client, pat, make.slot(doc, DAY)).json()["id"]
    cancelled = book(client, pat, make.slot(doc, 2 * DAY)).json()["id"]
    client.post(f"/appointments/{cancelled}/cancel", headers=as_patient(pat))

    up = client.get("/me/appointments", params={"when": "upcoming"}, headers=as_patient(pat))
    old = client.get("/me/appointments", params={"when": "past"}, headers=as_patient(pat))

    assert [a["id"] for a in up.json()] == [soon]
    assert [a["id"] for a in old.json()] == [str(past)]


# --- error codes ---------------------------------------------------------------


def test_book_past_slot_is_400(client: TestClient, make: Factory) -> None:
    resp = book(client, make.patient(), make.slot(make.doctor(), -HOUR))
    assert (resp.status_code, resp.json()["detail"]) == (400, "slot_in_past")


def test_reschedule_to_other_visit_type_is_400(client: TestClient, make: Factory) -> None:
    doc, pat = make.doctor(), make.patient()
    appt = book(client, pat, make.slot(doc, DAY, "Checkup")).json()["id"]
    other = make.slot(doc, 2 * DAY, "Follow-up")

    resp = client.post(
        f"/appointments/{appt}/reschedule", json={"new_slot_id": str(other)}, headers=as_patient(pat)
    )

    assert (resp.status_code, resp.json()["detail"]) == (400, "slot_mismatch")


def test_cancel_someone_elses_appointment_is_403(client: TestClient, make: Factory) -> None:
    owner, intruder = make.patient(), make.patient()
    appt = book(client, owner, make.slot(make.doctor(), DAY)).json()["id"]

    resp = client.post(f"/appointments/{appt}/cancel", headers=as_patient(intruder))

    assert (resp.status_code, resp.json()["detail"]) == (403, "not_your_appointment")


def test_book_unknown_slot_is_404(client: TestClient, make: Factory) -> None:
    resp = book(client, make.patient(), "00000000-0000-0000-0000-000000000000")
    assert (resp.status_code, resp.json()["detail"]) == (404, "slot_not_found")


def test_cancel_unknown_appointment_is_404(client: TestClient, make: Factory) -> None:
    resp = client.post(
        "/appointments/00000000-0000-0000-0000-000000000000/cancel",
        headers=as_patient(make.patient()),
    )
    assert (resp.status_code, resp.json()["detail"]) == (404, "appointment_not_found")


def test_book_taken_slot_is_409(client: TestClient, make: Factory) -> None:
    slot = make.slot(make.doctor(), DAY)
    assert book(client, make.patient(), slot).status_code == 201

    resp = book(client, make.patient(), slot)

    assert (resp.status_code, resp.json()["detail"]) == (409, "slot_not_open")


def test_missing_or_unknown_patient_is_401(client: TestClient) -> None:
    no_header = client.get("/me/appointments")
    bad_id = client.get("/me/appointments", headers={"X-Patient-Id": "not-a-uuid"})
    unknown = client.get(
        "/me/appointments", headers={"X-Patient-Id": "00000000-0000-0000-0000-000000000000"}
    )

    assert [r.status_code for r in (no_header, bad_id, unknown)] == [401, 401, 401]


def test_unexpected_db_error_is_generic_500(client: TestClient, db: psycopg.Connection, caplog) -> None:
    class BrokenConn:
        """Runs a query that fails with a real Postgres error."""

        def execute(self, *args, **kwargs):
            return db.execute("select * from table_that_does_not_exist")

    app.dependency_overrides[get_conn] = lambda: BrokenConn()
    try:
        with caplog.at_level(logging.ERROR, logger="app.db"):
            resp = client.get("/doctors")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "table_that_does_not_exist" not in resp.text
    assert "table_that_does_not_exist" in caplog.text  # logged for us
