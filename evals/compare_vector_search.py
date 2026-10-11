"""Exact search vs an HNSW index, on our data, with retrieval's real filters.

    uv run --project api evals/compare_vector_search.py

Runs every eval question (policy and record) three ways and reports rows returned,
overlap with the exact top 25, and ms per query:
  exact                    filters first, then compare every remaining vector (what we use)
  hnsw                     HNSW index, filters applied to its candidates
  hnsw + iterative_scan    pgvector 0.8 keeps scanning until enough rows pass the filters
The HNSW index is built inside a transaction that is rolled back: nothing changes.
"""

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.db import database_url  # noqa: E402
from app.rag.embed import embed_query  # noqa: E402
from app.rag.store import vector_literal  # noqa: E402

LIMIT = 25
SQL = (
    "select source_id from public.chunks where {where} and not sensitive"
    " order by embedding <=> %(q)s::extensions.vector limit %(limit)s"
)


def queries(conn) -> list[tuple[str, str, object]]:
    """(question, filter, patient) for every eval question."""
    out = [(f["question"], "source_type = 'policy'", None)
           for f in json.loads((ROOT / "evals" / "policy_facts.json").read_text())["facts"]]
    for c in json.loads((ROOT / "evals" / "retrieval_cases.json").read_text())["cases"]:
        first, last = c["patient"].split(" ", 1)
        pid = conn.execute("select id from public.patients where first_name = %s and last_name = %s",
                           (first, last)).fetchone()["id"]
        out.append((c["question"], "source_type = 'record' and patient_id = %(patient)s", pid))
    return out


def run(conn, qs, vectors) -> list[tuple[list[str], float]]:
    results = []
    for (_, where, patient), vec in zip(qs, vectors, strict=True):
        start = time.perf_counter()
        rows = conn.execute(SQL.format(where=where), {"q": vec, "patient": patient, "limit": LIMIT}).fetchall()
        results.append(([r["source_id"] for r in rows], (time.perf_counter() - start) * 1000))
    return results


def report(name: str, results, exact) -> None:
    short = sum(1 for ids, _ in results if len(ids) < LIMIT)
    empty = sum(1 for ids, _ in results if not ids)
    overlap = statistics.mean(len(set(ids) & set(e)) / len(e) for (ids, _), (e, _) in zip(results, exact, strict=True))
    times = sorted(ms for _, ms in results)
    print(f"  {name:24} returned <{LIMIT} rows: {short:2}/{len(results)} (empty {empty})  "
          f"overlap with exact top {LIMIT}: {overlap:.0%}  {statistics.mean(times):.2f} ms/query "
          f"(max {times[-1]:.2f})")


def main() -> None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        qs = queries(conn)
        vectors = [vector_literal(embed_query(q)) for q, _, _ in qs]
        total = conn.execute("select count(*) as n from public.chunks").fetchone()["n"]
        print(f"{len(qs)} queries over {total} chunks, top {LIMIT}\n")

        run(conn, qs, vectors)  # warm the cache before timing
        exact = run(conn, qs, vectors)
        report("exact", exact, exact)

        conn.execute("create index tmp_hnsw on public.chunks using hnsw (embedding extensions.vector_cosine_ops)")
        conn.execute("set local enable_seqscan = off")  # make the planner use the index
        conn.execute("set local enable_bitmapscan = off")
        conn.execute("set local enable_sort = off")  # else it filters first and sorts (= exact)
        plan = conn.execute("explain " + SQL.format(where="source_type = 'policy'"),
                            {"q": vectors[0], "patient": None, "limit": LIMIT}).fetchall()
        assert any("tmp_hnsw" in str(r) for r in plan), "planner did not use the HNSW index"
        run(conn, qs, vectors)
        report("hnsw", run(conn, qs, vectors), exact)
        conn.execute("set local hnsw.iterative_scan = relaxed_order")
        run(conn, qs, vectors)
        report("hnsw + iterative_scan", run(conn, qs, vectors), exact)
        conn.rollback()  # drops tmp_hnsw


if __name__ == "__main__":
    main()
