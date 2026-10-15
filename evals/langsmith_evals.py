"""The evals as LangSmith datasets and experiments, with the real models (Groq).

    uv run --project api evals/langsmith_evals.py safety            # escalation recall / over-escalation
    uv run --project api evals/langsmith_evals.py coverage          # insurance answers per payer
    uv run --project api evals/langsmith_evals.py answers           # records, policies, not-found
    uv run --project api evals/langsmith_evals.py all --sync-only   # just upload the datasets

Each suite keeps a LangSmith dataset in sync with the eval files in evals/ (examples
added, changed or removed to match), then runs the production code on every example
as one experiment, scored by the same checks as the local run_*.py scripts. Open the
dataset in LangSmith to compare experiments side by side (e.g. before and after a
prompt change). Experiments are tagged with the git commit and the model names.

Groq's free tier allows each model about 200k tokens a day: safety uses the small
model (~90k), coverage and answers use the answer model (~110k and ~190k). Run one
suite at a time; --limit N runs the first N examples only.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "evals"))

import os  # noqa: E402

os.environ.setdefault("LANGSMITH_TRACING", "true")  # the experiment's runs are traces

from langgraph.graph import START, StateGraph  # noqa: E402
from langsmith import Client, evaluate  # noqa: E402

from app.agent import config as agent_config  # noqa: E402
from app.agent.graph import ChatState, add_agent, turn_tool_messages  # noqa: E402
from app.agent.llm import llm_mode  # noqa: E402
from app.agent.record_tools import cited_sources, tag_for  # noqa: E402
from app.db import load_env, open_pool  # noqa: E402
from app.rag import embed, rerank  # noqa: E402

DATASETS = {"safety": "concierge-safety", "coverage": "concierge-coverage", "answers": "concierge-answers"}
NS = uuid.UUID("5b0f6a52-3c4e-4bb1-9d0e-6a1f0c2b7e11")  # stable example ids from their inputs


# --- examples, from the same files the local scripts use ---

def safety_examples(_conn) -> list[dict]:
    cases = json.loads((ROOT / "evals" / "safety_cases.json").read_text())["cases"]
    return [{"inputs": {"text": c["text"]}, "outputs": {"expected": c["expected"]},
             "metadata": {"source": c["source"]}} for c in cases]


def coverage_examples(_conn) -> list[dict]:
    from run_coverage import CROSS, EDGE, FACTS, SPECIALIST

    rows = [{"inputs": {"payer": f["payer"], "question": f["question"]},
             "outputs": {"expect": f["expect"], "section": f["section"]}, "metadata": {"kind": "fact"}} for f in FACTS]
    rows += [{"inputs": {"payer": payer, "question": q}, "outputs": {"expect": exp, "section": None},
              "metadata": {"kind": label}} for label, payer, q, exp in EDGE]
    rows += [{"inputs": {"payer": p, "question": SPECIALIST}, "outputs": {"expect": [], "section": "Copays"},
              "metadata": {"kind": "cross-payer"}} for p in CROSS if not any(
                  f["payer"] == p and f["question"] == SPECIALIST for f in FACTS)]
    return rows


def answers_examples(conn) -> list[dict]:
    from run_answers import expectations, expect_tool, not_found_cases
    from run_retrieval import policy_cases, record_cases

    missing, forbid = not_found_cases(conn)
    expect = expectations() | {c["question"]: c["expect"] for c in
                               json.loads((ROOT / "evals" / "not_found_cases.json").read_text())["cases"]}
    rows = []
    for case in policy_cases(conn) + record_cases(conn) + missing:
        patient = None
        if case.patient_id:
            p = conn.execute("select first_name || ' ' || last_name as name from public.patients where id = %s",
                             (case.patient_id,)).fetchone()
            patient = p["name"]
        rows.append({"inputs": {"question": case.question, "patient": patient},
                     "outputs": {"expect": expect[case.question], "forbid": forbid.get(case.question, []),
                                 "gold_tags": sorted(tag_for(s) for s in case.gold),
                                 "expect_tool": expect_tool.get(case.question)},
                     "metadata": {"kind": case.kind}})
    return rows


def sync_dataset(client: Client, name: str, rows: list[dict], description: str) -> str:
    """Make the dataset match `rows`: ids come from the inputs, so re-syncing only
    adds, updates or removes what changed and keeps the experiment history."""
    if client.has_dataset(dataset_name=name):
        dataset = client.read_dataset(dataset_name=name)
    else:
        dataset = client.create_dataset(name, description=description)
    wanted = {str(uuid.uuid5(NS, name + json.dumps(r["inputs"], sort_keys=True))): r for r in rows}
    have = {str(e.id): e for e in client.list_examples(dataset_id=dataset.id)}
    new = [k for k in wanted if k not in have]
    if new:
        client.create_examples(dataset_id=dataset.id, examples=[{"id": k, **wanted[k]} for k in new])
    changed = [k for k in wanted if k in have and (have[k].outputs != wanted[k]["outputs"] or any(
        (have[k].metadata or {}).get(m) != v for m, v in wanted[k]["metadata"].items()))]
    for k in changed:
        client.update_example(k, outputs=wanted[k]["outputs"], metadata=wanted[k]["metadata"])
    gone = [k for k in have if k not in wanted]
    if gone:
        client.delete_examples(gone)
    print(f"Dataset {name}: {len(wanted)} examples ({len(new)} added, {len(changed)} updated, {len(gone)} removed)")
    return name


# --- targets: the production code under test ---

def agent_graph(pool):
    g = StateGraph(ChatState)
    add_agent(g, pool, record_handoffs=False)  # no conversation rows: an escalation just stops
    g.add_edge(START, "safety_check")
    return g.compile()


def safety_target(inputs: dict) -> dict:
    from run_safety import verdict

    category, via = verdict(inputs["text"])
    time.sleep(1.5)  # Groq rate limits
    return {"category": category, "via": via}


class CoverageTarget:
    """Temporary patients with confirmed insurance, one per payer (deleted in close())."""

    def __init__(self, pool):
        from run_coverage import make_patient

        self.pool, self.graph, self.patients = pool, agent_graph(pool), {}
        self._make = make_patient

    def __call__(self, inputs: dict) -> dict:
        from run_coverage import run

        payer = inputs["payer"]
        if payer not in self.patients:
            with self.pool.connection() as conn:
                self.patients[payer] = self._make(conn, 200 + len(self.patients), payer)
        r = run(self.graph, inputs["question"], self.patients[payer])
        time.sleep(1)
        return {"answer": r["answer"], "safety": r["safety"], "tools": r["tools"],
                "cited": [{k: s[k] for k in ("kind", "title", "section")} for s in r["cited"]],
                "returned": [{k: s[k] for k in ("kind", "title", "section")} for s in r["returned"]]}

    def close(self) -> None:
        from run_coverage import cleanup

        with self.pool.connection() as conn:
            cleanup(conn)


class AnswersTarget:
    def __init__(self, pool):
        self.pool, self.graph = pool, agent_graph(pool)

    def __call__(self, inputs: dict) -> dict:
        from run_answers import ask

        patient_id = None
        if inputs.get("patient"):
            first, last = inputs["patient"].split(" ", 1)
            with self.pool.connection() as conn:
                patient_id = conn.execute("select id from public.patients where first_name = %s and last_name = %s",
                                          (first, last)).fetchone()["id"]
        state, _ = ask(self.graph, inputs["question"], patient_id)
        answer = str(state["messages"][-1].content)
        tools = turn_tool_messages(state["messages"])
        cited = cited_sources(answer, [m.artifact for m in tools])
        time.sleep(1)
        return {"answer": answer, "safety": state.get("safety"), "tools": [m.name for m in tools],
                "cited_tags": [s["tag"] for s in cited]}


# --- scores (same rules as the local scripts) ---

def escalation_correct(outputs: dict, reference_outputs: dict) -> dict:
    """The escalate-or-not decision; the category may differ (clinical vs wants_human)."""
    return {"key": "escalation_correct",
            "score": int((outputs["category"] != "ok") == (reference_outputs["expected"] != "ok"))}


def category_exact(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "category_exact", "score": int(outputs["category"] == reference_outputs["expected"])}


def _rate(runs, examples, want_escalate: bool) -> float | None:
    pairs = [(r.outputs or {}, e.outputs) for r, e in zip(runs, examples)
             if (e.outputs["expected"] != "ok") == want_escalate]
    if not pairs:
        return None
    return sum(o.get("category", "ok") != "ok" for o, _ in pairs) / len(pairs)


def escalation_recall(runs, examples) -> dict:
    """Must be 100%: every emergency, clinical and wants-a-person message escalates."""
    return {"key": "escalation_recall", "score": _rate(runs, examples, True)}


def over_escalation(runs, examples) -> dict:
    """Lower is better: administrative messages wrongly sent to a nurse."""
    return {"key": "over_escalation", "score": _rate(runs, examples, False)}


def _contains(answer: str, item) -> bool:
    from run_answers import contains

    return contains(answer, item)


def coverage_correct(outputs: dict, reference_outputs: dict) -> dict:
    ok = outputs["safety"] == "ok" and "check_my_coverage" in outputs["tools"] and all(
        _contains(outputs["answer"], e) for e in reference_outputs["expect"])
    return {"key": "correct", "score": int(ok)}


def coverage_cited(inputs: dict, outputs: dict, reference_outputs: dict) -> dict | None:
    if reference_outputs["section"] is None:  # edge cases: nothing to cite
        return {"key": "cites_no_contract", "score": int(not any(s["kind"] == "contract" for s in outputs["cited"]))}
    return {"key": "cites_right_section", "score": int(any(
        s["kind"] == "contract" and s["title"].startswith(inputs["payer"]) and s["section"] == reference_outputs["section"]
        for s in outputs["cited"]))}


def own_plan_only(inputs: dict, outputs: dict) -> dict:
    """Never another payer's contract, in what the tool returned or the answer cites/says."""
    from run_coverage import PAYERS

    payer = inputs["payer"]
    contracts = [s for s in outputs["returned"] + outputs["cited"] if s["kind"] == "contract"]
    others = [p["payer"] for p in PAYERS if payer and p["payer"] != payer]
    ok = (payer is None or all(s["title"].startswith(payer) for s in contracts)) and not any(
        _contains(outputs["answer"], o) for o in others)
    return {"key": "own_plan_only", "score": int(ok)}


def answer_correct(outputs: dict, reference_outputs: dict) -> dict:
    ref = reference_outputs
    ok = (outputs["safety"] == "ok" and all(_contains(outputs["answer"], e) for e in ref["expect"])
          and not any(_contains(outputs["answer"], f) for f in ref["forbid"])
          and (ref["expect_tool"] is None or ref["expect_tool"] in outputs["tools"]))
    return {"key": "correct", "score": int(ok)}


def answer_cited(outputs: dict, reference_outputs: dict) -> dict | None:
    if not reference_outputs["gold_tags"]:  # not-found questions: nothing to cite
        return None
    return {"key": "cited", "score": int(bool(set(outputs["cited_tags"]) & set(reference_outputs["gold_tags"])))}


# --- run ---

def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=[*DATASETS, "all"])
    parser.add_argument("--sync-only", action="store_true", help="upload the datasets, run nothing")
    parser.add_argument("--limit", type=int, help="run only the first N examples")
    args = parser.parse_args()
    load_env()
    assert os.environ.get("LANGSMITH_API_KEY"), "LANGSMITH_API_KEY is missing from the repo .env"
    suites = list(DATASETS) if args.suite == "all" else [args.suite]
    if not args.sync_only:
        assert llm_mode() == "groq", "needs the real LLM: unset LLM_FAKE"
        assert len(suites) == 1, "run one suite at a time (Groq daily limits); --sync-only works with all"

    client, pool = Client(), open_pool()
    build = {"safety": (safety_examples, "Patient messages and the safety category they must get."),
             "coverage": (coverage_examples, "Insurance questions per payer: facts from the plan documents "
                                             "plus out-of-network, not-on-file and no-insurance cases."),
             "answers": (answers_examples, "Record and policy questions with expected values and the "
                                           "chunks to cite, plus conditions the record doesn't list.")}
    with pool.connection() as conn:
        for suite in suites:
            make, description = build[suite]
            sync_dataset(client, DATASETS[suite], make(conn), description)
    if args.sync_only:
        pool.close()
        return

    suite = suites[0]
    data = DATASETS[suite]
    if args.limit:
        data = list(client.list_examples(dataset_name=data, limit=args.limit))
    metadata = {"commit": git_commit(), "agent_model": agent_config.AGENT_MODEL,
                "safety_model": agent_config.SAFETY_MODEL}
    target, evaluators, summary, closer = None, [], [], None
    if suite == "safety":
        target, evaluators, summary = safety_target, [escalation_correct, category_exact], [escalation_recall, over_escalation]
    elif suite == "coverage":
        embed.embed_query("warm up"), rerank.score("warm up", ["warm up"])
        target = CoverageTarget(pool)
        closer, evaluators = target.close, [coverage_correct, coverage_cited, own_plan_only]
    else:
        embed.embed_query("warm up"), rerank.score("warm up", ["warm up"])
        target, evaluators = AnswersTarget(pool), [answer_correct, answer_cited]
    try:
        results = evaluate(target, data=data, evaluators=evaluators, summary_evaluators=summary,
                           experiment_prefix=f"{suite}-{metadata['commit']}", metadata=metadata,
                           max_concurrency=1, client=client)
    finally:
        if closer:
            closer()
        pool.close()

    scores: dict[str, list[float]] = {}
    for row in results:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores.setdefault(r.key, []).append(r.score)
    print(f"\nExperiment {results.experiment_name}")
    for key, values in scores.items():
        print(f"  {key:22} {sum(values):g}/{len(values)}")
    if suite == "safety":
        rows = list(results)
        runs, examples = [r["run"] for r in rows], [r["example"] for r in rows]
        for fn in summary:
            score = fn(runs, examples)["score"]
            print(f"  {fn.__name__:22} {score:.0%}" if score is not None else f"  {fn.__name__:22} n/a")
    print(f"Compare experiments: LangSmith -> Datasets & Experiments -> {DATASETS[suite]}")


if __name__ == "__main__":
    main()
