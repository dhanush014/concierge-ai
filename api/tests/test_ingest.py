"""RAG ingestion: record and policy chunking, and the incremental sync. Fake embedder."""

import json
import uuid
from pathlib import Path

import psycopg
import pytest

from app.rag import embed
from app.rag.ingest import ingest_policies, ingest_records
from app.rag.policies import policy_chunks
from app.rag.records import bundle_chunks
from tests.rag_fixtures import EXPECTED, SENSITIVE, TODAY, bundle, fake_embed, policy_doc


@pytest.fixture
def embedded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Swap in the fake embedder; returns every text it was asked to embed."""
    seen: list[str] = []

    def fake(texts: list[str]) -> list[list[float]]:
        seen.extend(texts)
        return fake_embed(texts)

    monkeypatch.setattr(embed, "embed_texts", fake)
    return seen


# --- records: one chunk per event ---

def chunks_by_id(patient_id=None) -> dict:
    return {c.source_id: c for c in bundle_chunks(bundle("syn-1"), patient_id or uuid.uuid4(), TODAY)}


def test_one_chunk_per_event_with_type_and_date_in_the_text() -> None:
    chunks = chunks_by_id()
    assert set(chunks) == set(EXPECTED)
    for source_id, start in EXPECTED.items():
        assert chunks[source_id].content.startswith(start), chunks[source_id].content


def test_window_is_three_years_except_ongoing_items() -> None:
    chunks = chunks_by_id()
    # Outside the window and not ongoing: dropped. Future dates: dropped.
    for gone in ("Observation/old_lab", "Observation/future", "MedicationRequest/med_done_old", "Condition/cond_resolved_old"):
        assert f"fhir:{gone}" not in chunks
    # Still active, so kept with their original date.
    assert str(chunks["fhir:Condition/cond_active_old"].date) == "2015-06-01"
    assert str(chunks["fhir:AllergyIntolerance/allergy1"].date) == "2010-03-03"


def test_metadata() -> None:
    patient = uuid.uuid4()
    lab = chunks_by_id(patient)["fhir:Observation/lab1"]
    assert (lab.doc_title, lab.section, str(lab.date), lab.patient_id, lab.source_type) == (
        "Lab result", "Hemoglobin A1c", "2026-07-21", patient, "record")


def test_sensitive_tagged() -> None:
    chunks = chunks_by_id()
    assert {sid for sid, c in chunks.items() if c.sensitive} == SENSITIVE


def test_billing_and_other_skipped_types_produce_nothing() -> None:
    assert not any("Claim" in sid or "Medication/" in sid or "Patient" in sid for sid in chunks_by_id())


# --- policies: split by heading ---

def write_policy(tmp_path: Path, name: str = "parking.md", text: str | None = None) -> Path:
    path = tmp_path / name
    path.write_text(text if text is not None else policy_doc())
    return path


def test_policy_headings_kept(tmp_path: Path) -> None:
    chunks = {c.section: c for c in policy_chunks(write_policy(tmp_path), tmp_path)}
    assert chunks["Garage rates"].content.startswith("Parking > Garage rates\n\nThe first 30 minutes are free.")
    assert chunks["Garage rates > Weekly passes"].content.startswith("Parking > Garage rates > Weekly passes")
    assert chunks["Overview"].content.endswith("Intro line before any section.")
    assert all(c.doc_title == "Parking" and c.date is None and c.patient_id is None for c in chunks.values())


def test_long_sections_split_with_overlap(tmp_path: Path) -> None:
    parts = [c for c in policy_chunks(write_policy(tmp_path), tmp_path) if c.section == "Long section"]
    assert [c.source_id.rsplit("#", 1)[1] for c in parts] == ["0", "1", "2"]  # 700 words, 300-word windows
    first, second = (c.content.split("\n\n", 1)[1].split() for c in parts[:2])
    assert first[-40:] == second[:40]  # 40-word overlap
    assert all(c.content.startswith("Parking > Long section") for c in parts)


# --- the database sync ---

@pytest.fixture
def policy_ns(db: psycopg.Connection):
    ns = f"test-policy-{uuid.uuid4().hex[:8]}"
    yield ns
    db.execute("delete from public.chunks where source_id like %s", (f"{ns}:%",))


def count(db: psycopg.Connection, where: str, params) -> int:
    return db.execute(f"select count(*) as n from public.chunks where {where}", params).fetchone()["n"]


def test_policy_sync_skips_unchanged_and_removes_gone(db, tmp_path: Path, policy_ns: str, embedded: list[str]) -> None:
    write_policy(tmp_path)
    write_policy(tmp_path, "visiting.md", "# Visiting\n\n## Hours\n\n9 to 8.\n")
    first = ingest_policies(db, tmp_path, policy_ns)
    assert (first.new, first.embedded, first.removed) == (8, 8, 0)
    assert count(db, "source_id like %s and vector_dims(embedding) = 384", (f"{policy_ns}:%",)) == 8

    second = ingest_policies(db, tmp_path, policy_ns)
    assert (second.new, second.changed, second.unchanged, second.embedded) == (0, 0, 8, 0)

    write_policy(tmp_path, "visiting.md", "# Visiting\n\n## Hours\n\n10 to 8.\n")  # edit one section
    third = ingest_policies(db, tmp_path, policy_ns)
    assert (third.changed, third.embedded) == (1, 1)

    (tmp_path / "visiting.md").unlink()  # source gone
    fourth = ingest_policies(db, tmp_path, policy_ns)
    assert (fourth.removed, fourth.embedded) == (1, 0)
    assert count(db, "source_id like %s", (f"{policy_ns}:%",)) == 7


@pytest.fixture
def seeded(db: psycopg.Connection):
    """A patient whose synthea_id matches the fixture bundle; deleting it removes its chunks."""
    synthea_id = f"rag-test-{uuid.uuid4().hex[:8]}"
    patient = db.execute(
        "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
        " values (%s, 'Rag', 'Test', '1980-01-01') returning id", (synthea_id,),
    ).fetchone()["id"]
    yield synthea_id, patient
    db.execute("delete from public.patients where id = %s", (patient,))


def test_record_sync(db, tmp_path: Path, seeded, embedded: list[str]) -> None:
    synthea_id, patient = seeded
    (tmp_path / "Rag_Test.json").write_text(json.dumps(bundle(synthea_id)))
    (tmp_path / "Not_Seeded.json").write_text(json.dumps(bundle("nobody-has-this-id")))

    first = ingest_records(db, tmp_path, TODAY)
    assert (first.patients, first.skipped_files) == (1, ["Not_Seeded.json"])
    assert (first.counts.new, first.counts.embedded) == (len(EXPECTED), len(EXPECTED))
    rows = db.execute(
        "select source_id, sensitive, date, doc_title from public.chunks where patient_id = %s", (patient,)
    ).fetchall()
    assert {r["source_id"] for r in rows} == set(EXPECTED)
    assert {r["source_id"] for r in rows if r["sensitive"]} == SENSITIVE

    second = ingest_records(db, tmp_path, TODAY)
    assert (second.counts.unchanged, second.counts.embedded) == (len(EXPECTED), 0)

    # In 2030 everything that isn't ongoing has left the 3-year window and is removed.
    later = ingest_records(db, tmp_path, TODAY.replace(year=2030))
    ongoing = {"fhir:Condition/cond_active_old", "fhir:Condition/cond_depression",
               "fhir:MedicationRequest/med_active_old", "fhir:AllergyIntolerance/allergy1"}
    assert (later.counts.removed, later.counts.unchanged, later.counts.embedded) == (len(EXPECTED) - 4, 4, 0)
    left = db.execute("select source_id from public.chunks where patient_id = %s", (patient,)).fetchall()
    assert {r["source_id"] for r in left} == ongoing
