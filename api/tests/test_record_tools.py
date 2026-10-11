"""The agent's record tools: lab grouping, lists, isolation, sensitive, citations."""

import uuid
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent import record_tools as rt
from app.rag import embed, rerank
from app.rag.chunk import Chunk
from app.rag.store import Scope, sync
from tests.conftest import Factory, as_patient
from tests.fake_llm import FakeLLM, call
from tests.rag_fixtures import fake_embed


@pytest.fixture(autouse=True)
def fake_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed, "embed_texts", fake_embed)
    monkeypatch.setattr(rerank, "score", lambda q, texts: [0.0] * len(texts))


def rec(patient: uuid.UUID, key: str, title: str, section: str, when: str, text: str, sensitive: bool = False) -> Chunk:
    return Chunk(source_id=f"fhir:Tools/{patient}-{key}", source_type="record", doc_title=title, section=section,
                 content=f"{title}, {when}: {text}", date=date.fromisoformat(when), patient_id=patient,
                 sensitive=sensitive)


@pytest.fixture
def records(db: psycopg.Connection, make: Factory):
    """Aja with labs, meds, conditions and one sensitive condition; Bart with one lab."""
    aja, bart = make.patient(), make.patient()
    chunks = [
        rec(aja, "chol1", "Lab result", "Cholesterol [Mass/volume] in Serum or Plasma", "2024-01-10", "Cholesterol: 190 mg/dL"),
        rec(aja, "chol2", "Lab result", "Cholesterol [Mass/volume] in Serum or Plasma", "2025-01-10", "Cholesterol: 185 mg/dL"),
        rec(aja, "chol3", "Lab result", "Cholesterol [Mass/volume] in Serum or Plasma", "2026-01-10", "Cholesterol: 181 mg/dL"),
        rec(aja, "chol4", "Lab result", "Cholesterol [Mass/volume] in Serum or Plasma", "2026-06-10", "Cholesterol: 179 mg/dL"),
        rec(aja, "hdl", "Lab result", "Cholesterol in HDL [Mass/volume] in Serum or Plasma", "2026-06-10", "HDL: 50 mg/dL"),
        rec(aja, "ldl", "Lab result", "Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay", "2026-06-10", "LDL: 110 mg/dL"),
        rec(aja, "a1c", "Lab result", "Hemoglobin A1c/Hemoglobin.total in Blood", "2026-05-01", "A1c: 6.0 %"),
        rec(aja, "bp", "Vital sign", "Blood pressure panel with all children optional", "2026-05-01", "BP: 120/80"),
        rec(aja, "med-old", "Medication prescribed", "amoxicillin 500 MG", "2025-02-01", "amoxicillin 500 MG, status completed"),
        rec(aja, "med-new1", "Medication prescribed", "metformin 500 MG", "2024-03-01", "metformin 500 MG, status active"),
        rec(aja, "med-new2", "Medication prescribed", "metformin 500 MG", "2025-03-01", "metformin 500 MG, status active"),
        rec(aja, "cond", "Condition", "Prediabetes (finding)", "2020-01-01", "Prediabetes (finding), status active"),
        rec(aja, "secret", "Condition", "Major depression disorder", "2025-05-05", "Major depression disorder, status active", True),
        rec(bart, "chol", "Lab result", "Cholesterol [Mass/volume] in Serum or Plasma", "2026-07-01", "Cholesterol: 240 mg/dL BART"),
    ]
    sync(db, [c for c in chunks if c.patient_id == aja], Scope(patient_ids=(aja,)))
    sync(db, [c for c in chunks if c.patient_id == bart], Scope(patient_ids=(bart,)))
    return aja, bart  # chunks go when the factory deletes the patients (cascade)


def texts(lines) -> list[str]:
    return [t for _, t in lines]


def test_lab_results_group_by_test_newest_first(db, records) -> None:
    aja, _ = records
    lines = rt.lab_results(db, aja, "cholesterol", per_test=3)
    sections = [s.section for s, _ in lines]
    # total (3 latest of 4), HDL, LDL - not 5 values of one test
    assert sections.count("Cholesterol [Mass/volume] in Serum or Plasma") == 3
    assert {"Cholesterol in HDL [Mass/volume] in Serum or Plasma",
            "Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay"} <= set(sections)
    totals = [t for t in texts(lines) if t.endswith("mg/dL") and "Cholesterol:" in t]
    assert totals == ["Lab result, 2026-06-10: Cholesterol: 179 mg/dL", "Lab result, 2026-01-10: Cholesterol: 181 mg/dL",
                      "Lab result, 2025-01-10: Cholesterol: 185 mg/dL"]


@pytest.mark.parametrize(("name", "section"), [
    ("A1c", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    ("my latest LDL level", "Cholesterol in LDL [Mass/volume] in Serum or Plasma by Direct assay"),
    ("blood pressure", "Blood pressure panel with all children optional"),
])
def test_lab_names_match_by_words(db, records, name, section) -> None:
    aja, _ = records
    assert {s.section for s, _ in rt.lab_results(db, aja, name)} == {section}


def test_unknown_lab_name_falls_back_to_meaning(db, records) -> None:
    aja, _ = records
    lines = rt.lab_results(db, aja, "zzz unknown test")
    assert lines and all(s.title in ("Lab result", "Vital sign") for s, _ in lines)


def test_lists_collapse_repeats_and_put_current_first(db, records) -> None:
    aja, _ = records
    lines, total = rt.list_records(db, aja, "medications")
    meds = texts(lines)
    assert total == 2
    assert meds[0].startswith("Medication prescribed, 2025-03-01: metformin") and "(2 records, 2024-03-01 to 2025-03-01)" in meds[0]
    assert "amoxicillin" in meds[1] and len(meds) == 2


def test_sensitive_never_returned(db, records) -> None:
    aja, _ = records
    everything = texts(rt.list_records(db, aja, "conditions")[0]) + texts(rt.search_records(db, aja, "depression"))
    assert not any("depression" in t.lower() for t in everything)
    assert any("Prediabetes" in t for t in everything)


def test_only_the_callers_records(db, records) -> None:
    aja, bart = records
    assert not any("BART" in t for t in texts(rt.lab_results(db, aja, "cholesterol")))
    assert texts(rt.lab_results(db, bart, "cholesterol")) == ["Lab result, 2026-07-01: Cholesterol: 240 mg/dL BART"]


def test_render_tags_every_line_and_returns_sources(db, records) -> None:
    aja, _ = records
    text, sources = rt.render("Labs:", rt.lab_results(db, aja, "A1c"), "none")
    assert text.startswith("Labs:\n[S-") and len(sources) == 1
    assert sources[0] == {"tag": text[7:13], "kind": "record", "title": "Lab result",
                          "section": "Hemoglobin A1c/Hemoglobin.total in Blood", "date": "2026-05-01"}
    assert rt.render("Labs:", [], "No matching results.") == ("Labs:\nNo matching results.", [])


def test_cited_sources_in_order_and_only_real_tags() -> None:
    a = {"tag": "S-aaaa", "kind": "record", "title": "Lab result", "section": "A1c", "date": "2026-01-01"}
    b = {"tag": "S-bbbb", "kind": "policy", "title": "Parking", "section": "Validation", "date": None}
    answer = "Your A1c was 6 % [S-bbbb]. Also [S-aaaa, S-bbbb] and a made-up one [S-ffff]."
    assert rt.cited_sources(answer, [[a], [b]]) == [b, a]
    assert rt.cited_sources("no citations", [[a]]) == []
    assert rt.cited_sources("gpt-oss style【S-aaaa】【S-bbbb】.", [[a, b]]) == [a, b]


def test_sources_saved_with_the_reply(client: TestClient, records, fake_llm: FakeLLM) -> None:
    aja, _ = records
    tag = rt.tag_for(f"fhir:Tools/{aja}-a1c")
    fake_llm.agent_script = [call("get_lab_results", test_name="A1c"), AIMessage(f"Your A1c was 6.0 % [{tag}].")]
    resp = client.post("/me/chat", json={"message": "what is my A1c"}, headers=as_patient(aja))
    done = [line for line in resp.text.splitlines() if '"type": "done"' in line][0]
    assert f'"tag": "{tag}"' in done and '"section": "Hemoglobin A1c/Hemoglobin.total in Blood"' in done
    convo_id = resp.text.split('"id": "', 1)[1].split('"', 1)[0]
    body = client.get(f"/me/conversations/{convo_id}", headers=as_patient(aja)).json()
    assert body["messages"][-1]["sources"] == [{"tag": tag, "kind": "record", "title": "Lab result",
                                                "section": "Hemoglobin A1c/Hemoglobin.total in Blood", "date": "2026-05-01"}]
    assert body["messages"][0]["sources"] is None  # the patient's message has none


def test_a_cut_list_says_so(db, records, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.toolkit import make_tools

    aja, _ = records
    monkeypatch.setattr(rt, "LIST_LIMIT", 1)

    class Pool:  # the tool only needs pool.connection()
        def connection(self):
            from contextlib import nullcontext
            return nullcontext(db)

    tool = next(t for t in make_tools(Pool()) if t.name == "list_my_records")
    text = tool.invoke({"type": "tool_call", "id": "1", "name": "list_my_records",
                        "args": {"kind": "medications", "patient_id": str(aja)}}).content
    assert text.startswith("Your medications (showing 1 of 2; use search_my_records for others):")
