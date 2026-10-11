"""Retrieval eval: does the right chunk come back, and how high?

    uv run --project api evals/run_retrieval.py

17 policy questions (policy_facts.json, scope "policies") and 17 record questions
(retrieval_cases.json, scope "records"). The right chunks are looked up in the database
at run time, so re-ingesting doesn't break the eval. For each question the rank is the
position of the first right chunk among the top 25 by relevance (before the
records-newest-first display order). Reported with and without the reranker:
hit rate in the top 5, average rank (of those found in the top 25), misses, ms/query.
Needs the seed and scripts/ingest.py run first. Real models, local.
"""

import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.db import database_url  # noqa: E402
from app.rag import embed, rerank  # noqa: E402
from app.rag.retrieve import ranked  # noqa: E402

TOP_K, DEPTH = 5, 25


@dataclass
class Case:
    kind: str  # "policy" | "record"
    question: str
    patient_id: object | None
    gold: set[str]
    label: str


def policy_cases(conn) -> list[Case]:
    facts = json.loads((ROOT / "evals" / "policy_facts.json").read_text())["facts"]
    cases = []
    for f in facts:
        gold = {r["source_id"] for r in conn.execute(
            "select source_id from public.chunks where source_id like %s",
            (f"policy:{f['doc']}#{f['section']}#%",)).fetchall()}
        assert gold, f"no chunk for {f['doc']} > {f['section']}: run scripts/ingest.py"
        cases.append(Case("policy", f["question"], None, gold, f"{f['doc']} > {f['section']}"))
    return cases


def record_cases(conn) -> list[Case]:
    spec = json.loads((ROOT / "evals" / "retrieval_cases.json").read_text())["cases"]
    cases = []
    for c in spec:
        first, last = c["patient"].split(" ", 1)
        patient = conn.execute(
            "select id from public.patients where first_name = %s and last_name = %s", (first, last)
        ).fetchone()["id"]
        rows = conn.execute(
            "select source_id, date from public.chunks where patient_id = %s and doc_title = %s"
            " and section ilike %s and not sensitive", (patient, c["doc_title"], c["section"])).fetchall()
        assert rows, f"no chunk for {c}"
        if c["match"] == "latest":
            newest = max(r["date"] for r in rows)
            rows = [r for r in rows if r["date"] == newest]
        cases.append(Case("record", c["question"], patient, {r["source_id"] for r in rows},
                          f"{c['patient']}: {c['doc_title']} {c['section']} ({c['match']})"))
    return cases


def run(conn, cases: list[Case], use_reranker: bool) -> list[tuple[Case, int | None, float, str]]:
    out = []
    for case in cases:
        scope = "policies" if case.kind == "policy" else "records"
        start = time.perf_counter()
        got = ranked(conn, case.question, case.patient_id, scope, top_n=DEPTH, use_reranker=use_reranker)
        ms = (time.perf_counter() - start) * 1000
        rank = next((i for i, r in enumerate(got, 1) if r.source_id in case.gold), None)
        out.append((case, rank, ms, got[0].content.splitlines()[0][:70] if got else "(nothing)"))
    return out


def summary(rows) -> str:
    ranks = [r for _, r, _, _ in rows]
    hits = sum(1 for r in ranks if r is not None and r <= TOP_K)
    found = [r for r in ranks if r is not None]
    times = [ms for _, _, ms, _ in rows]
    avg = f"{statistics.mean(found):.2f}" if found else "-"
    return (f"hit@{TOP_K} {hits}/{len(rows)} ({hits / len(rows):.0%})  avg rank {avg}  "
            f"missed (not in top {DEPTH}) {len(ranks) - len(found)}  "
            f"{statistics.mean(times):.0f} ms/query (p95 {sorted(times)[int(0.95 * (len(times) - 1))]:.0f})")


def main() -> None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        cases = policy_cases(conn) + record_cases(conn)
        embed.embed_query("warm up")  # load both models before timing
        rerank.score("warm up", ["warm up"])
        results = {mode: run(conn, cases, mode == "with reranker") for mode in ("without reranker", "with reranker")}

    print(f"Retrieval eval: {len(cases)} questions\n")
    for mode, rows in results.items():
        print(f"{mode.upper()}")
        for kind in ("policy", "record"):
            print(f"  {kind + 's':9} {summary([r for r in rows if r[0].kind == kind])}")
        print(f"  {'all':9} {summary(rows)}\n")

    print(f"Questions where the right chunk is not #1 (rank without -> with reranker):")
    without = {c.question: r for c, r, _, _ in results["without reranker"]}
    for case, rank, _, top in results["with reranker"]:
        if rank != 1 or without[case.question] != 1:
            fmt = lambda r: str(r) if r else "miss"  # noqa: E731
            print(f"  {fmt(without[case.question]):>4} -> {fmt(rank):<4} {case.question}  [{case.label}]")
            print(f"       top result now: {top}")


if __name__ == "__main__":
    main()
