"""Coverage answer eval with the real LLM (Groq): right plan, right answer, never another payer's.

    uv run --project api evals/run_coverage.py

Creates temporary patients with confirmed insurance (one per payer, plus edge cases),
runs the real agent graph (safety check + tool loop) and deletes them afterwards.

The 16 contract facts (contract_facts.json), each asked by a patient on that payer:
  correct    every expected value appears in the answer
  cited      the answer cites the fact's doc + section
  own plan   every contract source the tool returned and the answer cites is that
             payer's, and the answer names no other payer
Edge cases: out of network (Northstar), not on file, no confirmed insurance: the answer
says so and cites no contract.
Cross-payer: "What is my specialist copay?" for three payers gives three different
answers, each from its own plan. About 70 Groq calls.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "evals"))

os.environ.setdefault("LANGSMITH_TRACING", "false")

from langgraph.graph import START, StateGraph  # noqa: E402

from app.agent.config import BILLING_PHONE  # noqa: E402
from app.agent.graph import ChatState, add_agent, turn_tool_messages  # noqa: E402
from app.agent.llm import llm_mode  # noqa: E402
from app.agent.record_tools import cited_sources  # noqa: E402
from app.db import open_pool  # noqa: E402
from app.rag import embed, rerank  # noqa: E402
from run_answers import ask, contains, normalize  # noqa: E402

PAYERS = json.loads((ROOT / "data" / "payers.json").read_text())["payers"]
FACTS = json.loads((ROOT / "evals" / "contract_facts.json").read_text())["facts"]
TAG = f"eval-coverage-{uuid.uuid4().hex[:8]}"

# (label, payer on the card or None for no insurance, question, expected items)
EDGE = [
    ("out of network", "Northstar Benefits", "What is my specialist copay?",
     [["out of network", "out-of-network"], BILLING_PHONE]),
    ("not on file", "Acme Mutual", "Is an MRI covered?", [["not on file", "isn't on file", "not have", "don't have"], BILLING_PHONE]),
    ("no insurance", None, "What is my deductible?", ["Documents"]),
]
CROSS = ["Riverbend Health", "Summit Health Partners", "Allegheny Shield"]
SPECIALIST = "What is my specialist copay?"


def make_patient(conn, n: int, payer: str | None) -> uuid.UUID:
    pid = conn.execute(
        "insert into public.patients (synthea_id, first_name, last_name, birth_date)"
        " values (%s, 'Eval', %s, '1980-01-01') returning id", (f"{TAG}-{n}", f"Coverage{n}"),
    ).fetchone()["id"]
    if payer:
        plan = next((p["plan_name"] for p in PAYERS if p["payer"] == payer), None)
        conn.execute("insert into public.patient_insurance (patient_id, payer, plan_name, status)"
                     " values (%s, %s, %s, 'confirmed')", (pid, payer, plan))
    return pid


def cleanup(conn) -> None:
    ids = [r["id"] for r in conn.execute("select id from public.patients where synthea_id like %s", (f"{TAG}-%",))]
    conn.execute("delete from public.patient_insurance where patient_id = any(%s)", (ids,))
    conn.execute("delete from public.patients where id = any(%s)", (ids,))


def run(graph, question: str, pid) -> dict:
    state, secs = ask(graph, question, pid)
    answer = str(state["messages"][-1].content)
    tools = turn_tool_messages(state["messages"])
    returned = [s for m in tools for s in (m.artifact or [])]
    return {"answer": answer, "secs": secs, "safety": state.get("safety"), "tools": [m.name for m in tools],
            "returned": returned, "cited": cited_sources(answer, [m.artifact for m in tools])}


def own_plan(r: dict, payer: str) -> bool:
    contracts = [s for s in r["returned"] + r["cited"] if s["kind"] == "contract"]
    others = [p["payer"] for p in PAYERS if p["payer"] != payer]
    return all(s["title"].startswith(payer) for s in contracts) and not any(contains(r["answer"], o) for o in others)


def main() -> None:
    assert llm_mode() == "groq", "run_coverage.py needs the real LLM: unset LLM_FAKE"
    pool = open_pool()
    g = StateGraph(ChatState)
    add_agent(g, pool, record_handoffs=False)
    g.add_edge(START, "safety_check")
    graph = g.compile()
    embed.embed_query("warm up")
    rerank.score("warm up", ["warm up"])

    with pool.connection() as conn:
        on = {p["payer"]: make_patient(conn, i, p["payer"]) for i, p in enumerate(PAYERS) if p["in_network"]}
        edge = [(label, make_patient(conn, 100 + i, payer), q, exp) for i, (label, payer, q, exp) in enumerate(EDGE)]
    try:
        facts = []
        print(f"Contract facts ({len(FACTS)}):")
        for i, f in enumerate(FACTS, 1):
            r = run(graph, f["question"], on[f["payer"]])
            row = r | {"payer": f["payer"], "question": f["question"],
                       "correct": r["safety"] == "ok" and all(contains(r["answer"], e) for e in f["expect"]),
                       "cited_right": any(s["kind"] == "contract" and s["title"].startswith(f["payer"])
                                          and s["section"] == f["section"] for s in r["cited"]),
                       "own": own_plan(r, f["payer"])}
            facts.append(row)
            marks = "".join("✓" if row[k] else "✗" for k in ("correct", "cited_right", "own"))
            print(f"{i:2}. {marks} {r['secs']:4.1f}s [{f['payer']}] {f['question']}  tools={r['tools']}")
            time.sleep(1)

        print("\nEdge cases:")
        edges = []
        for label, pid, q, exp in edge:
            r = run(graph, q, pid)
            row = r | {"label": label, "question": q,
                       "correct": r["safety"] == "ok" and all(contains(r["answer"], e) for e in exp)
                       and "check_my_coverage" in r["tools"],
                       "no_contract": not any(s["kind"] == "contract" for s in r["returned"] + r["cited"])}
            edges.append(row)
            marks = "".join("✓" if row[k] else "✗" for k in ("correct", "no_contract"))
            print(f"    {marks} {r['secs']:4.1f}s [{label}] {q}")
            time.sleep(1)

        print(f"\nCross-payer: {SPECIALIST!r}")
        cross = {}
        for payer in CROSS:
            r = run(graph, SPECIALIST, on[payer])
            cross[payer] = r
            print(f"    [{payer}] own plan {'✓' if own_plan(r, payer) else '✗'}: " + r["answer"].replace("\n", " ")[:160])
            time.sleep(1)
    finally:
        with pool.connection() as conn:
            cleanup(conn)

    n = len(facts)
    print("\nRESULTS")
    for key, name in (("correct", "correct"), ("cited_right", "cites right section"), ("own", "own plan only")):
        print(f"  facts  {name:22} {sum(r[key] for r in facts)}/{n}")
    for key, name in (("correct", "says so + next step"), ("no_contract", "cites no contract")):
        print(f"  edges  {name:22} {sum(r[key] for r in edges)}/{len(edges)}")
    texts = {normalize(r["answer"]) for r in cross.values()}
    print(f"  cross  different answers       {len(texts)}/{len(CROSS)}   "
          f"own plan only {sum(own_plan(r, p) for p, r in cross.items())}/{len(CROSS)}")
    every = facts + edges + list(cross.values())
    print(f"  avg {sum(r['secs'] for r in every) / len(every):.1f}s per question")

    bad = [r for r in facts if not all(r[k] for k in ("correct", "cited_right", "own"))]
    bad += [r for r in edges if not all(r[k] for k in ("correct", "no_contract"))]
    print("\nNOT RIGHT:" if bad else "\nEverything right.")
    for r in bad:
        print(f"\n  [{r.get('payer') or r.get('label')}] {r['question']}  safety={r['safety']} tools={r['tools']}")
        print(f"    cited: {[(s['title'], s['section']) for s in r['cited']]}")
        print("    answer: " + r["answer"].replace("\n", " ")[:400])
    pool.close()


if __name__ == "__main__":
    main()
