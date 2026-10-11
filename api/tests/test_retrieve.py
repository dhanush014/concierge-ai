"""Retrieval filters and ordering. Fake embedder and reranker (no models)."""

import re
import uuid
from datetime import date

import psycopg
import pytest

from app.rag import embed, rerank
from app.rag.chunk import Chunk
from app.rag.retrieve import retrieve
from app.rag.store import Scope, sync
from tests.rag_fixtures import fake_embed


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@pytest.fixture(autouse=True)
def fake_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed_texts", fake_embed)
    # Reranker: shared words between question and chunk.
    monkeypatch.setattr(rerank, "score", lambda q, texts: [float(len(words(q) & words(t))) for t in texts])


def record(patient: uuid.UUID, tag: str, key: str, title: str, when: str, text: str, sensitive: bool = False) -> Chunk:
    return Chunk(
        source_id=f"fhir:Test/{tag}-{key}", source_type="record", doc_title=title, section=key,
        content=f"{title}, {when}: {text}", date=date.fromisoformat(when), patient_id=patient, sensitive=sensitive,
    )


@pytest.fixture
def world(db: psycopg.Connection):
    """Aja and Bart (patient rows only) with a few record chunks each, some sensitive, and
    two test policy chunks. Deleting the patients removes their chunks (cascade)."""
    tag = uuid.uuid4().hex[:8]
    ids = {}
    for name in ("Aja", "Bart"):
        ids[name] = db.execute(
            "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
            " values (%s, %s, 'Retrieve', '1980-01-01') returning id", (f"retrieve-{tag}-{name}", name),
        ).fetchone()["id"]
    nobody = db.execute(
        "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
        " values (%s, 'Nobody', 'Retrieve', '1980-01-01') returning id", (f"retrieve-{tag}-nobody",),
    ).fetchone()["id"]
    aja, bart = ids["Aja"], ids["Bart"]
    chunks = {
        "aja": [
            record(aja, tag, "a1c-old", "Lab result", "2025-01-10", "Hemoglobin A1c: 6.1 %"),
            record(aja, tag, "a1c-new", "Lab result", "2026-07-21", "Hemoglobin A1c: 5.9 %"),
            record(aja, tag, "visit", "Visit", "2026-03-10", "General examination at Riverside"),
            record(aja, tag, "phq9", "Survey", "2026-05-01", "PHQ-9 depression score: 4", sensitive=True),
        ],
        "bart": [
            record(bart, tag, "a1c", "Lab result", "2026-08-01", "Hemoglobin A1c: 7.2 % Bart"),
            record(bart, tag, "aspirin", "Medication prescribed", "2025-02-02", "aspirin 81 MG Bart"),
            record(bart, tag, "depression", "Condition", "2025-03-03", "Major depression disorder Bart", sensitive=True),
        ],
    }
    sync(db, chunks["aja"], Scope(patient_ids=(aja,)))
    sync(db, chunks["bart"], Scope(patient_ids=(bart,)))
    ns = f"test-retrieve-{tag}"
    policies = [
        Chunk(source_id=f"{ns}:parking.md#Validation#0", source_type="policy", doc_title="Parking",
              section="Validation", content="Parking > Validation\n\nParking validation gives 3 hours free."),
        Chunk(source_id=f"{ns}:lab.md#Fasting#0", source_type="policy", doc_title="Lab prep",
              section="Fasting", content="Lab prep > Fasting\n\nFast 8 to 12 hours before a lipid panel."),
    ]
    sync(db, policies, Scope(namespace=ns))
    yield {"aja": aja, "bart": bart, "nobody": nobody, "chunks": chunks, "tag": tag}
    db.execute("delete from public.chunks where source_id like %s", (f"{ns}:%",))
    db.execute("delete from public.patients where id = any(%s)", ([aja, bart, nobody],))


QUESTIONS = ["what was my A1c", "Bart aspirin depression", "PHQ-9 depression score", "parking validation", "hello"]


@pytest.mark.parametrize("scope", ["records", "both"])
@pytest.mark.parametrize("use_reranker", [True, False])
def test_aja_never_gets_barts_chunks(db, world, scope, use_reranker) -> None:
    barts = {c.source_id for c in world["chunks"]["bart"]}
    for q in QUESTIONS:
        got = retrieve(db, q, world["aja"], scope, top_n=25, use_reranker=use_reranker)
        assert not barts & {r.source_id for r in got}, q


@pytest.mark.parametrize("scope", ["records", "policies", "both"])
@pytest.mark.parametrize("use_reranker", [True, False])
def test_sensitive_chunks_never_returned(db, world, scope, use_reranker) -> None:
    sensitive = {c.source_id for side in world["chunks"].values() for c in side if c.sensitive}
    for who in ("aja", "bart"):
        for q in QUESTIONS:
            got = retrieve(db, q, world[who], scope, top_n=25, use_reranker=use_reranker)
            assert not sensitive & {r.source_id for r in got}, (who, q)


def test_scope_filters(db, world) -> None:
    assert {r.source_type for r in retrieve(db, "A1c", world["aja"], "records", top_n=25)} == {"record"}
    assert {r.source_type for r in retrieve(db, "A1c", None, "policies", top_n=25)} == {"policy"}
    both = retrieve(db, "A1c parking", world["aja"], "both", top_n=25)
    assert {r.source_type for r in both} == {"record", "policy"}
    with pytest.raises(ValueError):
        retrieve(db, "A1c", None, "records")


def test_records_newest_first(db, world) -> None:
    got = retrieve(db, "A1c visit", world["aja"], "records", top_n=10)
    dates = [r.date for r in got]
    assert len(dates) == 3 and dates == sorted(dates, reverse=True)


def test_both_picks_top_n_by_score_then_orders_for_display(db, world) -> None:
    from app.rag.retrieve import ranked

    q = "parking validation hours A1c"
    best = ranked(db, q, world["aja"], "both", top_n=4)
    assert [r.rerank_score for r in best] == sorted((r.rerank_score for r in best), reverse=True)
    shown = retrieve(db, q, world["aja"], "both", top_n=4)
    assert {r.source_id for r in shown} == {r.source_id for r in best}  # same top N, picked by score
    types = [r.source_type for r in shown]
    assert types == sorted(types, key=lambda t: t != "record")  # records first, then policies


def test_display_order() -> None:
    from app.rag.retrieve import Retrieved, display_order

    def item(sid: str, kind: str, when: str | None, score: float) -> Retrieved:
        return Retrieved(sid, kind, "t", None, date.fromisoformat(when) if when else None, "c", 0.5, score)

    best_first = [item("p1", "policy", None, 9), item("r-old", "record", "2024-01-01", 8),
                  item("p2", "policy", None, 7), item("r-new", "record", "2026-01-01", 6)]
    assert [r.source_id for r in display_order(best_first)] == ["r-new", "r-old", "p1", "p2"]


def test_reranker_scores_and_top_n(db, world) -> None:
    got = retrieve(db, "Hemoglobin A1c", world["aja"], "records", top_n=2)
    assert len(got) == 2 and all(r.rerank_score is not None for r in got)
    assert {r.section for r in got} == {"a1c-old", "a1c-new"}  # the two best-scoring


def test_without_reranker_order_is_similarity(db, world) -> None:
    from app.rag.retrieve import ranked

    got = ranked(db, "Hemoglobin A1c", world["aja"], "both", top_n=6, use_reranker=False)
    sims = [r.similarity for r in got]
    assert sims == sorted(sims, reverse=True) and all(r.rerank_score is None for r in got)


def test_patient_without_records_still_gets_policies(db, world) -> None:
    got = retrieve(db, "parking validation", world["nobody"], "both", top_n=5)
    assert got and {r.source_type for r in got} == {"policy"}
