"""The database, not Python, prevents double booking under concurrent requests."""

import threading
from datetime import timedelta

import psycopg
from fastapi.testclient import TestClient

from tests.conftest import Factory, as_patient

THREADS = 10


def test_concurrent_bookings_exactly_one_wins(
    client: TestClient, make: Factory, db: psycopg.Connection
) -> None:
    slot = make.slot(make.doctor(), timedelta(days=1))
    patients = [make.patient() for _ in range(THREADS)]
    start_together = threading.Barrier(THREADS)
    statuses: list[int] = []
    lock = threading.Lock()

    def try_book(patient_id) -> None:
        start_together.wait()  # release all threads at the same instant
        resp = client.post(
            "/appointments", json={"slot_id": str(slot)}, headers=as_patient(patient_id)
        )
        with lock:
            statuses.append(resp.status_code)

    threads = [threading.Thread(target=try_book, args=(p,)) for p in patients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(statuses) == [201] + [409] * (THREADS - 1)
    booked = db.execute(
        "select count(*) as n from public.appointments where slot_id = %s and status = 'booked'",
        (slot,),
    ).fetchone()
    assert booked["n"] == 1
