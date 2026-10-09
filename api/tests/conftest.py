"""Shared fixtures. Tests make their own rows relative to now() and delete them after.

Requires local Supabase running (supabase start) and DATABASE_URL in the repo .env.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.db import database_url
from app.main import app


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:  # runs lifespan, so the pool opens and closes
        yield c


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url(), autocommit=True, row_factory=dict_row) as conn:
        yield conn


def as_patient(patient_id: uuid.UUID) -> dict[str, str]:
    return {"X-Patient-Id": str(patient_id)}


class Factory:
    """Creates test rows and remembers them so they can be deleted afterwards."""

    def __init__(self, db: psycopg.Connection) -> None:
        self.db = db
        self.tag = uuid.uuid4().hex[:8]
        self.doctor_ids: list[uuid.UUID] = []
        self.patient_ids: list[uuid.UUID] = []

    def doctor(self, specialty: str = "Test Medicine") -> uuid.UUID:
        row = self.db.execute(
            "insert into public.doctors (name, specialty) values (%s, %s) returning id",
            (f"Dr. Test {self.tag}", specialty),
        ).fetchone()
        self.doctor_ids.append(row["id"])
        return row["id"]

    def patient(self) -> uuid.UUID:
        n = len(self.patient_ids)
        row = self.db.execute(
            "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
            " values (%s, 'Test', %s, '1990-01-01') returning id",
            (f"test-{self.tag}-{n}", f"Patient{n}"),
        ).fetchone()
        self.patient_ids.append(row["id"])
        return row["id"]

    def slot(
        self, doctor_id: uuid.UUID, starts_in: timedelta, visit_type: str = "Checkup"
    ) -> uuid.UUID:
        """A 30-minute slot starting `starts_in` from now (negative = in the past)."""
        start = datetime.now(timezone.utc) + starts_in
        row = self.db.execute(
            "insert into public.slots (doctor_id, start_at, end_at, visit_type)"
            " values (%s, %s, %s, %s) returning id",
            (doctor_id, start, start + timedelta(minutes=30), visit_type),
        ).fetchone()
        return row["id"]

    def book_directly(self, patient_id: uuid.UUID, slot_id: uuid.UUID) -> uuid.UUID:
        """Insert an appointment without book_slot (needed for past appointments)."""
        row = self.db.execute(
            "insert into public.appointments (patient_id, slot_id) values (%s, %s) returning id",
            (patient_id, slot_id),
        ).fetchone()
        return row["id"]

    def cleanup(self) -> None:
        self.db.execute(
            "delete from public.appointments where patient_id = any(%s)"
            " or slot_id in (select id from public.slots where doctor_id = any(%s))",
            (self.patient_ids, self.doctor_ids),
        )
        self.db.execute("delete from public.slots where doctor_id = any(%s)", (self.doctor_ids,))
        self.db.execute("delete from public.doctors where id = any(%s)", (self.doctor_ids,))
        self.db.execute("delete from public.patients where id = any(%s)", (self.patient_ids,))


@pytest.fixture
def make(db: psycopg.Connection) -> Iterator[Factory]:
    factory = Factory(db)
    yield factory
    factory.cleanup()
