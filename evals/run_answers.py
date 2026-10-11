"""Answer eval with the real LLM (Groq): is the answer right, and does it cite the source?

    uv run --project api evals/run_answers.py

Runs the real agent graph (safety check + tool loop) on the 17 policy facts
(policy_facts.json), the 17 record questions (retrieval_cases.json) and the not-found
questions (not_found_cases.json: a condition the record doesn't list; the answer must
not say they don't have it - see 'forbid'; nothing to cite):
  correct  every expected value appears in the answer (case-insensitive; dashes and
           spaces normalized; an item that is a list is a set of alternatives)
  cited    at least one source the answer cites is a right chunk (same gold chunks
           as evals/run_retrieval.py)
and lists the tools each question used. Needs GROQ_API_KEY in .env, the seed and
scripts/ingest.py. About 100 Groq calls.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "evals"))

import os  # noqa: E402

os.environ.setdefault("LANGSMITH_TRACING", "false")

from langgraph.graph import START, StateGraph  # noqa: E402

from app.agent.graph import ChatState, add_agent, turn_input, turn_tool_messages  # noqa: E402
from run_retrieval import Case  # noqa: E402
from app.agent.llm import llm_mode  # noqa: E402
from app.agent.record_tools import cited_sources, tag_for  # noqa: E402
from app.db import open_pool  # noqa: E402
from app.rag import embed, rerank  # noqa: E402
from run_retrieval import policy_cases, record_cases  # noqa: E402

RETRIES = 3


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub("[‘’ʼ]", "'", text)  # curly apostrophes -> "'"
    return re.sub(r"[‐-―−]", "-", text)  # typographic dashes -> "-"


def contains(answer: str, item) -> bool:
    options = item if isinstance(item, list) else [item]
    return any(normalize(o) in normalize(answer) for o in options)


def expectations() -> dict[str, list]:
    facts = json.loads((ROOT / "evals" / "policy_facts.json").read_text())["facts"]
    cases = json.loads((ROOT / "evals" / "retrieval_cases.json").read_text())["cases"]
    return {f["question"]: f["expect"] for f in facts} | {c["question"]: c["expect"] for c in cases}


expect_tool: dict[str, str | None] = {}  # question -> a tool that must have been called


def not_found_cases(conn) -> tuple[list[Case], dict[str, list]]:
    spec = json.loads((ROOT / "evals" / "not_found_cases.json").read_text())["cases"]
    cases, forbid = [], {}
    for c in spec:
        first, last = c["patient"].split(" ", 1)
        pid = conn.execute("select id from public.patients where first_name = %s and last_name = %s",
                           (first, last)).fetchone()["id"]
        cases.append(Case("not-found", c["question"], pid, set(), c["patient"]))
        forbid[c["question"]] = c["forbid"]
        expect_tool[c["question"]] = c.get("expect_tool")
    return cases, forbid


def ask(graph, question: str, patient_id) -> tuple[dict, float]:
    patient = patient_id or "00000000-0000-0000-0000-000000000000"  # policy questions: no records needed
    for attempt in range(1, RETRIES + 1):
        start = time.perf_counter()
        try:
            return graph.invoke(turn_input(patient, question)), time.perf_counter() - start
        except Exception as exc:  # rate limits: wait and retry
            if attempt == RETRIES:
                raise
            print(f"   retry {attempt} after {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(15 * attempt)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["policy", "record", "not-found"], help="run one kind of question")
    args = parser.parse_args()
    assert llm_mode() == "groq", "run_answers.py needs the real LLM: unset LLM_FAKE"
    pool = open_pool()
    g = StateGraph(ChatState)
    add_agent(g, pool, record_handoffs=False)  # no conversation rows: an escalation just stops
    g.add_edge(START, "safety_check")
    graph = g.compile()
    with pool.connection() as conn:
        missing, forbid = not_found_cases(conn)
        cases = policy_cases(conn) + record_cases(conn) + missing
    if args.only:
        cases = [c for c in cases if c.kind == args.only]
    expect = expectations() | {
        c["question"]: c["expect"] for c in json.loads((ROOT / "evals" / "not_found_cases.json").read_text())["cases"]}
    embed.embed_query("warm up")
    rerank.score("warm up", ["warm up"])

    results = []
    for i, case in enumerate(cases, 1):
        state, secs = ask(graph, case.question, case.patient_id)
        answer = str(state["messages"][-1].content)
        tools = turn_tool_messages(state["messages"])
        cited = cited_sources(answer, [m.artifact for m in tools])
        gold_tags = {tag_for(s) for s in case.gold}
        row = {
            "kind": case.kind, "question": case.question, "safety": state.get("safety"),
            "correct": state.get("safety") == "ok" and all(contains(answer, e) for e in expect[case.question])
            and not any(contains(answer, f) for f in forbid.get(case.question, []))
            and (expect_tool.get(case.question) is None or expect_tool[case.question] in [m.name for m in tools]),
            "cited": any(s["tag"] in gold_tags for s in cited) if case.gold else None,  # not-found: n/a
            "tools": [m.name for m in tools],
            "answer": answer, "secs": secs,
        }
        results.append(row)
        mark = ("✓" if row["correct"] else "✗") + {True: "✓", False: "✗", None: "-"}[row["cited"]]
        print(f"{i:2}. {mark} {secs:4.1f}s {case.question}  tools={row['tools']}")
        time.sleep(1)  # be gentle with Groq rate limits

    print("\nRESULTS (correct = expected value in the answer; cited = cites a right source)")
    for kind in ("policy", "record", "not-found"):
        rows = [r for r in results if r["kind"] == kind]
        if not rows:
            continue
        cited = f"{sum(bool(r['cited']) for r in rows)}/{len(rows)}" if kind != "not-found" else "n/a"
        print(f"  {kind + 's':9} correct {sum(r['correct'] for r in rows)}/{len(rows)}  "
              f"cited {cited}  "
              f"avg {sum(r['secs'] for r in rows) / len(rows):.1f}s")
    print(f"  {'all':9} correct {sum(r['correct'] for r in results)}/{len(results)}  "
          f"cited {sum(bool(r['cited']) for r in results)}/{sum(r['cited'] is not None for r in results)}")
    calls = {}
    for r in results:
        for t in r["tools"]:
            calls[t] = calls.get(t, 0) + 1
    print(f"  tools called: {calls}   avg calls/question {sum(len(r['tools']) for r in results) / len(results):.1f}")

    print("\nNOT CORRECT OR NOT CITED:")
    for r in results:
        if not r["correct"] or r["cited"] is False:
            print(f"\n  [{r['kind']}] {r['question']}  safety={r['safety']} correct={r['correct']} cited={r['cited']}")
            print(f"    tools: {r['tools']}")
            print("    answer: " + r["answer"].replace("\n", " ")[:400])
    for r in results:
        if r["kind"] == "not-found" and r["correct"]:
            print(f"\n  [not-found, passed] {r['question']}\n    answer: " + r["answer"].replace("\n", " ")[:400])
    pool.close()


if __name__ == "__main__":
    main()
