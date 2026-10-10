"""Shared fixtures. Tests make their own rows relative to now() and delete them after.

Requires local Supabase running (supabase start) and the repo .env. Test patients and
staff are real Supabase Auth users with real access tokens.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

# Tests never send traces. Set before app code loads .env (which won't override it).
os.environ["LANGSMITH_TRACING"] = "false"

from app import storage  # noqa: E402
from app.agent import llm  # noqa: E402
from app.db import database_url  # noqa: E402
from app.main import app  # noqa: E402
from tests.fake_llm import FakeLLM  # noqa: E402
from tests.supabase_auth import SupabaseAuth  # noqa: E402

# patient_id -> access token, filled by Factory.patient()
TOKENS: dict[uuid.UUID, str] = {}


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:  # runs lifespan, so the pool opens and closes
        yield c


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """Every test gets the scripted LLM, so no test can reach Groq."""
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat_model", fake)
    return fake


@pytest.fixture(scope="session")
def supabase_auth() -> SupabaseAuth:
    return SupabaseAuth()


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url(), autocommit=True, row_factory=dict_row) as conn:
        yield conn


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def as_patient(patient_id: uuid.UUID) -> dict[str, str]:
    return bearer(TOKENS[patient_id])


class Factory:
    """Creates test rows and remembers them so they can be deleted afterwards."""

    def __init__(self, db: psycopg.Connection, auth: SupabaseAuth) -> None:
        self.db = db
        self.auth = auth
        self.tag = uuid.uuid4().hex[:8]
        self.doctor_ids: list[uuid.UUID] = []
        self.patient_ids: list[uuid.UUID] = []
        self.user_ids: list[str] = []

    def _login(
        self, label: str, role: str | None = None, patient_id: uuid.UUID | None = None
    ) -> tuple[str, str]:
        """Create an auth user (+ profile when role is given), then sign in.

        The profile must exist before sign-in so the token gets its user_role claim.
        """
        email = f"test-{self.tag}-{label}-{len(self.user_ids)}@example.test"
        user_id, password = self.auth.create_user(email)
        self.user_ids.append(user_id)
        if role is not None:
            self.db.execute(
                "insert into public.profiles (id, role, patient_id, display_name)"
                " values (%s, %s, %s, %s)",
                (user_id, role, patient_id, f"Test {role}"),
            )
        return user_id, self.auth.sign_in(email, password)

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
        patient_id = row["id"]
        self.patient_ids.append(patient_id)
        _, TOKENS[patient_id] = self._login("patient", "patient", patient_id)
        return patient_id

    def staff_token(self) -> str:
        return self._login("staff", "staff")[1]

    def token_without_profile(self) -> str:
        return self._login("noprofile")[1]

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

    def document_row(self, patient_id: uuid.UUID, filename: str, kind: str = "insurance_card") -> uuid.UUID:
        """A documents row with no file behind it (enough for read-only queries)."""
        doc_id = uuid.uuid4()
        self.db.execute(
            "insert into public.documents (id, patient_id, kind, storage_path, original_filename,"
            " content_type, size_bytes) values (%s, %s, %s, %s, %s, 'image/png', 100)",
            (doc_id, patient_id, kind, f"{patient_id}/{doc_id}.png", filename),
        )
        return doc_id

    def cleanup(self) -> None:
        convos = self.db.execute(
            "delete from public.conversations where patient_id = any(%s) returning id",
            (self.patient_ids,),
        ).fetchall()  # messages go with them (on delete cascade)
        graph = getattr(app.state, "chat_graph", None)
        for convo in convos:
            if graph is not None:
                graph.checkpointer.delete_thread(str(convo["id"]))
        self.db.execute(
            "delete from public.appointments where patient_id = any(%s)"
            " or slot_id in (select id from public.slots where doctor_id = any(%s))",
            (self.patient_ids, self.doctor_ids),
        )
        self.db.execute("delete from public.slots where doctor_id = any(%s)", (self.doctor_ids,))
        self.db.execute("delete from public.doctors where id = any(%s)", (self.doctor_ids,))
        docs = self.db.execute(
            "delete from public.documents where patient_id = any(%s) returning storage_path",
            (self.patient_ids,),
        ).fetchall()
        for doc in docs:
            storage.remove(doc["storage_path"])
        for user_id in self.user_ids:  # also deletes their profiles (on delete cascade)
            self.auth.delete_user(user_id)
        self.db.execute("delete from public.patients where id = any(%s)", (self.patient_ids,))
        for patient_id in self.patient_ids:
            TOKENS.pop(patient_id, None)


@pytest.fixture
def make(db: psycopg.Connection, supabase_auth: SupabaseAuth) -> Iterator[Factory]:
    factory = Factory(db, supabase_auth)
    yield factory
    factory.cleanup()
