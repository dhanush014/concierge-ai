"""Safety classifier eval with the real model (Groq): escalation recall and
over-escalation, on evals/safety_cases.json.

    uv run --project api evals/run_safety.py [--only heldout]

Mirrors the production cascade: the strict regex decides when it matches, otherwise
the LLM decides. The LLM gets a generous timeout and retries here, so a slow Groq
response measures the model, not the 3-second production fallback.
  recall          escalate cases (emergency/clinical/wants_human) that escalated
  over-escalation ok cases that escalated
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.agent import safety  # noqa: E402
from app.agent.llm import llm_mode  # noqa: E402

RETRIES, TIMEOUT = 4, 30


def verdict(text: str) -> tuple[str, str]:
    """(category, source) as production would decide, without the 3 s fallback."""
    strict = safety.strict_match(text)
    if strict:
        return strict[0], "regex"
    for attempt in range(1, RETRIES + 1):
        try:
            with ThreadPoolExecutor(1) as pool:
                return pool.submit(safety.classify, text).result(timeout=TIMEOUT)[0], "llm"
        except Exception as exc:  # rate limit or timeout: wait and retry
            if attempt == RETRIES:
                raise
            print(f"   retry {attempt} ({type(exc).__name__})")
            time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="only cases with this source (e.g. heldout)")
    args = parser.parse_args()
    assert llm_mode() == "groq", "needs the real LLM: unset LLM_FAKE"

    cases = json.loads((ROOT / "evals" / "safety_cases.json").read_text())["cases"]
    if args.only:
        cases = [c for c in cases if c["source"] == args.only]
    rows = []
    for c in cases:
        category, source = verdict(c["text"])
        rows.append({**c, "got": category, "via": source})
        time.sleep(1.5)  # Groq rate limits

    def report(label: str, subset: list[dict]) -> None:
        esc = [r for r in subset if r["expected"] != "ok"]
        ok = [r for r in subset if r["expected"] == "ok"]
        caught = sum(r["got"] != "ok" for r in esc)
        over = sum(r["got"] != "ok" for r in ok)
        right = sum(r["got"] == r["expected"] for r in subset)
        print(f"  {label:10} recall {caught}/{len(esc)} ({caught / max(len(esc), 1):.0%})   "
              f"over-escalation {over}/{len(ok)} ({over / max(len(ok), 1):.0%})   "
              f"exact category {right}/{len(subset)}")

    print(f"Safety eval: {len(rows)} cases (model: {safety.llm.MODELS['safety']})")
    for source in sorted({r["source"] for r in rows}):
        report(source, [r for r in rows if r["source"] == source])
    report("all", rows)
    wrong = [r for r in rows if (r["got"] == "ok") != (r["expected"] == "ok")]
    print("\nWrong escalate/ok decision:" if wrong else "\nNo wrong escalate/ok decisions.")
    for r in wrong:
        print(f"  expected {r['expected']:11} got {r['got']:11} via {r['via']:5} [{r['source']}] {r['text']}")


if __name__ == "__main__":
    main()
