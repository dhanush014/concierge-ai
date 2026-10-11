"""Phase 5 step 1: insurance tables, payer seed, contract ingestion, sample cards."""

import json
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from PIL import Image

from app.db import database_url
from app.rag import embed, rerank
from app.rag.ingest import ingest_contracts
from app.rag.retrieve import retrieve
from tests.conftest import Factory
from tests.rag_fixtures import fake_embed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

PAYERS = json.loads((ROOT / "data" / "payers.json").read_text())["payers"]


@pytest.fixture(autouse=True)
def fake_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed_texts", fake_embed)
    monkeypatch.setattr(rerank, "score", lambda q, texts: [0.0] * len(texts))


@pytest.fixture
def tx():
    """A connection whose changes are rolled back."""
    with psycopg.connect(database_url()) as conn:
        yield conn
        conn.rollback()


# --- tables ---

def test_one_row_per_payer_and_plan(tx) -> None:
    tx.execute("insert into public.network_contracts (payer, plan_name, in_network) values ('T', 'P', true)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        tx.execute("insert into public.network_contracts (payer, plan_name, in_network) values ('T', 'P', false)")


def test_patient_insurance_status(db: psycopg.Connection, make: Factory) -> None:
    patient = make.patient()
    db.execute("insert into public.patient_insurance (patient_id, payer) values (%s, 'Riverbend Health')", (patient,))
    assert db.execute("select status from public.patient_insurance where patient_id = %s",
                      (patient,)).fetchone()["status"] == "extracted"
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into public.patient_insurance (patient_id, payer, status) values (%s, 'X', 'guessed')",
                   (patient,))
    db.execute("delete from public.patient_insurance where patient_id = %s", (patient,))


@pytest.mark.parametrize(("source_type", "payer"), [("contract", None), ("policy", "Riverbend Health")])
def test_only_contract_chunks_have_a_payer(tx, source_type, payer) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        tx.execute(
            "insert into public.chunks (source_id, source_type, payer, doc_title, content, content_hash, embedding)"
            " values ('t:x', %s, %s, 't', 'c', 'h', %s::extensions.vector)",
            (source_type, payer, "[" + ",".join(["0"] * 384) + "]"),
        )


# --- seed ---

def test_seed_loads_payers_json(tx) -> None:
    from seed import seed_network_contracts

    with tx.cursor() as cur:
        assert seed_network_contracts(cur) == len(PAYERS)
        rows = cur.execute("select payer, plan_name, in_network from public.network_contracts").fetchall()
    assert sorted(rows) == sorted((p["payer"], p["plan_name"], p["in_network"]) for p in PAYERS)


def test_payers_file_shape() -> None:
    assert sum(not p["in_network"] for p in PAYERS) == 1
    assert 4 <= sum(p["in_network"] for p in PAYERS) <= 5
    contracts = {p.stem for p in (ROOT / "data" / "contracts").glob("*.md")}
    assert contracts == {p["slug"] for p in PAYERS if p["in_network"]}  # one doc per in-network payer
    for doc in (ROOT / "data" / "contracts").glob("*.md"):
        assert "Fictional" in doc.read_text().split("\n\n", 2)[1], doc.name  # says so up front


# --- contract ingestion ---

@pytest.fixture
def contract_docs(tmp_path: Path, db: psycopg.Connection):
    ns = f"test-contract-{uuid.uuid4().hex[:8]}"
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "plan-a.md").write_text("# Plan A\n\n## Copays\n\nSpecialist visit: $50.\n\n## Not covered\n\nHearing aids.\n")
    (tmp_path / "docs" / "plan-b.md").write_text("# Plan B\n\n## Copays\n\nSpecialist visit: $35.\n")
    payers = tmp_path / "payers.json"
    payers.write_text(json.dumps({"payers": [{"slug": "plan-a", "payer": f"{ns} A"}, {"slug": "plan-b", "payer": f"{ns} B"}]}))
    yield tmp_path / "docs", payers, ns
    db.execute("delete from public.chunks where source_id like %s", (f"{ns}:%",))


def test_contract_chunks_are_tagged_with_their_payer(db, contract_docs) -> None:
    folder, payers, ns = contract_docs
    first = ingest_contracts(db, folder, ns, payers)
    assert (first.new, first.embedded) == (3, 3)
    rows = db.execute("select source_type, payer, section from public.chunks where source_id like %s order by source_id",
                      (f"{ns}:%",)).fetchall()
    assert [(r["source_type"], r["payer"], r["section"]) for r in rows] == [
        ("contract", f"{ns} A", "Copays"), ("contract", f"{ns} A", "Not covered"), ("contract", f"{ns} B", "Copays")]
    assert ingest_contracts(db, folder, ns, payers).embedded == 0  # unchanged: nothing re-embedded


def test_a_doc_without_a_payer_is_an_error(db, contract_docs) -> None:
    folder, payers, ns = contract_docs
    (folder / "mystery.md").write_text("# Mystery\n\n## Copays\n\n$1.\n")
    with pytest.raises(ValueError, match="mystery.md"):
        ingest_contracts(db, folder, ns, payers)


def test_contract_search_is_per_payer_and_policies_never_mix_in(db, contract_docs) -> None:
    folder, payers, ns = contract_docs
    ingest_contracts(db, folder, ns, payers)
    got = retrieve(db, "specialist copay", None, "contracts", top_n=10, payer=f"{ns} B")
    assert [r.content.split("\n")[0] for r in got] == ["Plan B > Copays"]
    assert all(r.source_type == "policy" for r in retrieve(db, "specialist copay", None, "policies", top_n=25))
    with pytest.raises(ValueError):
        retrieve(db, "copay", None, "contracts")  # a payer is required


# --- cards ---

@pytest.fixture(scope="module")
def cards(tmp_path_factory):
    from make_cards import make_cards

    out = tmp_path_factory.mktemp("cards")
    return out, make_cards(out)


def test_every_card_is_written_and_described(cards) -> None:
    out, results = cards
    truth = json.loads((out / "truth.json").read_text())["cards"]
    assert [c["file"] for c in truth] == [t.file for t, _ in results]
    for c in truth:
        assert (out / c["file"]).exists()
        assert c["member_id"] and c["group_number"] and c["plan_name"]
    assert {c["variation"] for c in truth} == {"clean", "rotated", "lowres", "alt-layout"}
    assert {c["in_network"] for c in truth} == {True, False}  # an out-of-network card too


def test_every_card_is_marked_sample(cards) -> None:
    _, results = cards
    for truth, drawn in results:
        assert "SAMPLE" in drawn, truth.file  # the diagonal watermark
        assert any("NOT A REAL INSURANCE CARD" in t for t in drawn), truth.file  # the banner


def test_variations_share_the_identity_and_differ_in_shape(cards) -> None:
    out, results = cards
    by_file = {t.file: t for t, _ in results}
    assert by_file["aja-rotated.png"].member_id == by_file["aja.png"].member_id == by_file["aja-lowres.jpg"].member_id
    clean, tilted, low = (Image.open(out / f).size for f in ("aja.png", "aja-rotated.png", "aja-lowres.jpg"))
    assert tilted[0] > clean[0] and low[0] < clean[0]


def test_cards_are_reproducible(cards, tmp_path: Path) -> None:
    from make_cards import make_cards

    out, _ = cards
    make_cards(tmp_path)
    assert json.loads((tmp_path / "truth.json").read_text()) == json.loads((out / "truth.json").read_text())
    assert (tmp_path / "aja.png").read_bytes() == (out / "aja.png").read_bytes()
