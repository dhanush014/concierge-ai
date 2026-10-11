"""Card extraction eval with the real vision model (Groq): does each field come back right?

    uv run --project api evals/run_extraction.py

Reads every card in data/cards/ with the production extraction code and compares each
field with truth.json, ignoring case and spaces:
  ✓  right                ∅  left null though readable (a miss, but the form highlights it)
  ✗  wrong value          (worst: it looks filled in)
For a field made unreadable on purpose (truth.json expect_null):
  ⊘  null, as it should   ✗  a guess (any value)   R  read it anyway, correctly (the card
                                                      wasn't as unreadable as intended)
Reports a card x field table, accuracy per variation and wrong vs blank totals.
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


def grade(got: str | None, want: str, unreadable: bool) -> str:
    if unreadable:
        return "⊘" if got is None else ("R" if same(got, want) else "✗")
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
        marks = {f: grade(getattr(got, f), card[f], f in card.get("expect_null", [])) for f in FIELDS}
        rows.append((card, got, marks, secs))

    width = max(len(c["file"]) for c in cards)
    print(f"Card extraction: {len(cards)} cards, model {VISION_MODEL}\n")
    print(f"{'card':{width}}  {'variation':10}  " + "  ".join(f"{SHORT[f]:>9}" for f in FIELDS) + "   time")
    for card, _, marks, secs in rows:
        print(f"{card['file']:{width}}  {card['variation']:10}  " + "  ".join(f"{marks[f]:>9}" for f in FIELDS)
              + f"  {secs:4.1f}s")

    print("\nBy variation (right = ✓ or ⊘):")
    for variation in ("clean", "rotated", "lowres", "alt-layout", "cropped", "glare", "smudged"):
        marks = [m for c, _, ms, _ in rows if c["variation"] == variation for m in ms.values()]
        if not marks:
            continue
        right = marks.count("✓") + marks.count("⊘")
        print(f"  {variation:10} {right}/{len(marks)} ({right / len(marks):.0%})   wrong {marks.count('✗')}, "
              f"blank {marks.count('∅') + marks.count('⊘')}, read-anyway {marks.count('R')}")
    every = [m for _, _, ms, _ in rows for m in ms.values()]
    right = every.count("✓") + every.count("⊘")
    print(f"  {'all':10} {right}/{len(every)} ({right / len(every):.0%})")
    unread = [ms[f] for c, _, ms, _ in rows for f in c.get("expect_null", [])]
    print(f"\nWrong vs blank:\n  readable fields:    wrong {sum(m == '✗' for c, _, ms, _ in rows for f, m in ms.items() if f not in c.get('expect_null', []))}, "
          f"blank {every.count('∅')}"
          f"\n  unreadable fields:  blank {unread.count('⊘')}/{len(unread)} (right), guessed {unread.count('✗')}, "
          f"read anyway {unread.count('R')}")

    misses = [(c, f, getattr(g, f), c[f]) for c, g, ms, _ in rows for f in FIELDS if ms[f] not in ("✓", "⊘")]
    print("\nNot right:" if misses else "\nEvery field right.")
    for card, field, got, want in misses:
        print(f"  {card['file']}: {field} read {got!r}, card says {want!r}")


if __name__ == "__main__":
    main()
