"""What the agent's tools look up. Plain SQL over the caller's own data; the patient id
always comes from the login (see toolkit.py), never from the LLM.

Every line handed to the LLM starts with a source tag like [S-3f2a]; the answer cites
those tags and the chat route turns them into the "Sources" list under the reply. A
tag is a short hash of the source id, so it's stable however many tools run.
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID

import psycopg

from app.rag.retrieve import Retrieved, retrieve

LAB_TYPES = ("Lab result", "Vital sign")
RECORD_KINDS = {
    "medications": "Medication prescribed",
    "conditions": "Condition",
    "allergies": "Allergy",
    "immunizations": "Immunization",
    "visits": "Visit",
}
# Words that say nothing about which test: "what was my latest cholesterol level".
LAB_STOPWORDS = {"my", "the", "a", "an", "of", "in", "level", "levels", "test", "tests", "result",
                 "results", "value", "values", "latest", "last", "recent", "most", "what", "was", "is"}
LIST_LIMIT = 30  # distinct items per list; more than any seeded patient has


@dataclass(frozen=True)
class Source:
    tag: str  # "S-3f2a", what the answer cites
    kind: str  # record | policy | appointment | document | contract
    title: str  # "Lab result", "Parking", "Appointment"
    section: str | None  # "Hemoglobin A1c", "Validation"
    date: str | None  # ISO date, when there is one


def tag_for(source_id: str) -> str:
    return "S-" + hashlib.sha1(source_id.encode()).hexdigest()[:4]


def source(source_id: str, kind: str, title: str, section: str | None, when: date | None) -> Source:
    return Source(tag_for(source_id), kind, title, section, when.isoformat() if when else None)


Line = tuple[Source, str]  # (where it came from, the text the LLM sees)


def render(header: str, lines: list[Line], empty: str) -> tuple[str, list[dict]]:
    """Tool output: text for the LLM plus the sources as an artifact (not shown to it)."""
    if not lines:
        return f"{header}\n{empty}", []
    text = "\n".join(f"[{s.tag}] {t}" for s, t in lines)
    return f"{header}\n{text}", [asdict(s) for s, _ in lines]


def from_chunk(r: Retrieved | dict) -> Line:
    get = (lambda k: getattr(r, k)) if isinstance(r, Retrieved) else r.__getitem__
    kind = get("source_type")
    return source(get("source_id"), kind, get("doc_title"), get("section"), get("date")), get("content")


# --- lab results and vitals ---

def _lab_words(test_name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", test_name.lower()) if w not in LAB_STOPWORDS]


def lab_results(conn: psycopg.Connection, patient_id: UUID, test_name: str, per_test: int = 3, max_tests: int = 6) -> list[Line]:
    """Latest few values per matching test, newest test first. "cholesterol" matches total,
    HDL and LDL; each test name matches when all the query's words appear in it. No
    match: the nearest lab/vital chunks by meaning instead."""
    rows = conn.execute(
        "select source_id, source_type, doc_title, section, date, content from public.chunks"
        " where patient_id = %s and doc_title = any(%s) and not sensitive order by date desc, source_id",
        (patient_id, list(LAB_TYPES)),
    ).fetchall()
    words = _lab_words(test_name)
    matched = [r for r in rows if words and all(w in (r["section"] or "").lower() for w in words)]
    if not matched:
        near = retrieve(conn, test_name, patient_id, "records", top_n=10, use_reranker=False)
        sections = {r.section for r in near if r.doc_title in LAB_TYPES}
        matched = [r for r in rows if r["section"] in sections]
    by_test: dict[str, list[dict]] = defaultdict(list)
    for r in matched:  # already newest first
        if len(by_test[r["section"]]) < per_test:
            by_test[r["section"]].append(r)
    tests = sorted(by_test.values(), key=lambda rs: rs[0]["date"], reverse=True)[:max_tests]
    return [from_chunk(r) for rs in tests for r in rs]


# --- lists: medications, conditions, allergies, immunizations, visits ---

def _status(content: str) -> str | None:
    m = re.search(r"status (\w+)\s*$", content)
    return m.group(1) if m else None


def list_records(conn: psycopg.Connection, patient_id: UUID, kind: str) -> tuple[list[Line], int]:
    """(one line per distinct item, how many distinct items there are). Duplicates
    collapsed, current items first, then newest; at most LIST_LIMIT lines."""
    doc_title = RECORD_KINDS[kind]
    rows = conn.execute(
        "select source_id, source_type, doc_title, section, date, content from public.chunks"
        " where patient_id = %s and doc_title = %s and not sensitive order by date desc, source_id",
        (patient_id, doc_title),
    ).fetchall()
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["section"]].append(r)
    lines = []
    for items in groups.values():
        latest, first = items[0], items[-1]
        status = _status(latest["content"])
        text = latest["content"]
        if len(items) > 1:
            text += f" ({len(items)} records, {first['date']} to {latest['date']})"
        lines.append((status == "active", latest["date"], from_chunk(latest)[0], text))
    lines.sort(key=lambda x: (x[0], x[1]), reverse=True)  # active first, then newest
    return [(s, t) for _, _, s, t in lines[:LIST_LIMIT]], len(lines)


# --- searches ---

def search_records(conn: psycopg.Connection, patient_id: UUID, query: str) -> list[Line]:
    return [from_chunk(r) for r in retrieve(conn, query, patient_id, "records", top_n=5, use_reranker=False)]


@dataclass(frozen=True)
class Coverage:
    header: str  # what the tool says first: the plan and its network status, or what to do
    lines: list[Line]  # contract lines (in network only)


def coverage(conn: psycopg.Connection, patient_id: UUID, question: str) -> Coverage:
    """The patient's confirmed insurance decides everything; the LLM only asks the question.
    In network: search THAT payer's contract chunks only (payer from the database match)."""
    from app.agent.config import BILLING_PHONE
    from app.insurance.match import match_network

    ins = conn.execute(
        "select payer, plan_name from public.patient_insurance where patient_id = %s and status = 'confirmed'"
        " order by created_at desc, id desc limit 1",
        (patient_id,),
    ).fetchone()
    if ins is None:
        return Coverage("No confirmed insurance on file. To check coverage, the patient should upload a photo "
                        "of their insurance card in the Documents tab, choose Read card, and confirm the details.", [])
    match = match_network(conn, ins["payer"], ins["plan_name"])
    plan = " - ".join(p for p in (ins["payer"], ins["plan_name"]) if p)
    if match.status == "out_of_network":
        return Coverage(f"The patient's plan ({plan}) is OUT OF NETWORK with Riverside Health. We have no "
                        f"coverage details for it. Visits may cost more; call billing at {BILLING_PHONE}.", [])
    if match.status == "not_on_file":
        return Coverage(f"The patient's plan ({plan}) is NOT ON FILE with Riverside Health, so we can't check "
                        f"coverage. Call billing at {BILLING_PHONE}, or their insurer.", [])
    found = retrieve(conn, question, None, "contracts", top_n=4, use_reranker=True, payer=match.payer)
    return Coverage(f"The patient's plan ({plan}) is IN NETWORK with Riverside Health. "
                    f"Plan document excerpts ({match.payer}):", [from_chunk(r) for r in found])


def search_policies(conn: psycopg.Connection, query: str) -> list[Line]:
    """Reranked: on the 4.2 eval the reranker improved policy rank (1.12 -> 1.06)."""
    return [from_chunk(r) for r in retrieve(conn, query, None, "policies", top_n=4, use_reranker=True)]


# "[S-3f2a]", "[S-3f2a, S-91bc]", or gpt-oss's own citation brackets "【S-3f2a】".
CITE = re.compile(r"[\[【]([^\]】]*S-[0-9a-f]{4}[^\]】]*)[\]】]")


def cited_sources(answer: str, artifacts: list[list[dict]]) -> list[dict]:
    """The sources an answer cites, in the order first cited. Tags that no tool returned
    in this turn (made up by the model) are dropped."""
    known = {s["tag"]: s for batch in artifacts for s in (batch or [])}
    order: list[str] = []
    for group in CITE.findall(answer):
        for tag in re.findall(r"S-[0-9a-f]{4}", group):
            if tag in known and tag not in order:
                order.append(tag)
    return [known[t] for t in order]
