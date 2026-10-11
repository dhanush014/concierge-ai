"""Card extraction eval with the real vision model (Groq): does each field come back right?

    uv run --project api evals/run_extraction.py

Reads every card in data/cards/ with the production extraction code and compares each
field with truth.json, ignoring case and spaces:
  ✓  right      ∅  left null (the form highlights it for the patient)
  ✗  wrong value (worse: it looks filled in)
Reports a card x field table, accuracy per variation (clean, rotated, low-res, other
layout) and totals. 6 vision calls.
"""

import json
import mimetypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.agent.config import VISION_MODEL  # noqa: E402
from app.agent.llm import llm_mode  # noqa: E402
from app.insurance.extract import read_card  # noqa: E402
from app.models import CardFields  # noqa: E402

CARDS = ROOT / "data" / "cards"
FIELDS = list(CardFields.model_fields)
SHORT = {"payer": "payer", "plan_name": "plan", "member_name": "name", "member_id": "member id", "group_number": "group"}


def same(a: str | None, b: str | None) -> bool:
    squash = lambda s: "".join((s or "").lower().split())  # noqa: E731
    return squash(a) == squash(b)


def grade(got: str | None, want: str) -> str:
    if got is None:
        return "∅"
    return "✓" if same(got, want) else "✗"


def main() -> None:
    assert llm_mode() == "groq", "needs the real vision model: unset LLM_FAKE"
    cards = json.loads((CARDS / "truth.json").read_text())["cards"]
    rows = []
    for card in cards:
        path = CARDS / card["file"]
        start = time.perf_counter()
        for attempt in range(3):  # rate limits
            try:
                got = read_card(path.read_bytes(), mimetypes.guess_type(path.name)[0])
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                print(f"   retry ({type(exc).__name__})")
                time.sleep(15)
        secs = time.perf_counter() - start
        marks = {f: grade(getattr(got, f), card[f]) for f in FIELDS}
        rows.append((card, got, marks, secs))

    width = max(len(c["file"]) for c in cards)
    print(f"Card extraction: {len(cards)} cards, model {VISION_MODEL}\n")
    print(f"{'card':{width}}  {'variation':10}  " + "  ".join(f"{SHORT[f]:>9}" for f in FIELDS) + "   time")
    for card, _, marks, secs in rows:
        print(f"{card['file']:{width}}  {card['variation']:10}  " + "  ".join(f"{marks[f]:>9}" for f in FIELDS)
              + f"  {secs:4.1f}s")

    print("\nAccuracy by variation (fields right / fields):")
    for variation in ("clean", "rotated", "lowres", "alt-layout"):
        marks = [m for c, _, ms, _ in rows if c["variation"] == variation for m in ms.values()]
        right = marks.count("✓")
        print(f"  {variation:10} {right}/{len(marks)} ({right / len(marks):.0%})   "
              f"wrong {marks.count('✗')}, null {marks.count('∅')}")
    every = [m for _, _, ms, _ in rows for m in ms.values()]
    print(f"  {'all':10} {every.count('✓')}/{len(every)} ({every.count('✓') / len(every):.0%})   "
          f"wrong {every.count('✗')}, null {every.count('∅')}")

    misses = [(c, f, getattr(g, f), c[f]) for c, g, ms, _ in rows for f in FIELDS if ms[f] != "✓"]
    print("\nNot right:" if misses else "\nEvery field right.")
    for card, field, got, want in misses:
        print(f"  {card['file']}: {field} read {got!r}, card says {want!r}")


if __name__ == "__main__":
    main()
