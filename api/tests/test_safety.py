"""Safety cascade: strict regex -> LLM -> loose-regex fallback. Fake LLM only."""

import json
from pathlib import Path

import pytest

from app.agent import config, safety
from app.agent.safety_prompt import SAFETY_PROMPT
from tests.fake_llm import FakeLLM

CASES_FILE = Path(__file__).resolve().parents[2] / "evals" / "safety_cases.json"
CASES = json.loads(CASES_FILE.read_text())["cases"]


def verdict(category: str, reason: str = "fake") -> str:
    return json.dumps({"category": category, "reason": reason})


# --- each category through the strict regex (no LLM call) ---

@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I think I'm having a heart attack", "emergency"),
        ("I feel dizzy", "clinical"),
        ("can I talk to a real person", "wants_human"),
    ],
)
def test_strict_regex_decides_without_llm(fake_llm: FakeLLM, text: str, category: str) -> None:
    result = safety.check(text)
    assert (result.category, result.source) == (category, "regex")
    assert fake_llm.calls("safety") == 0


def test_curly_apostrophe_still_matches() -> None:
    assert safety.check("I’m having trouble breathing").category == "emergency"


# --- each category through the LLM ---

@pytest.mark.parametrize("category", ["emergency", "clinical", "wants_human", "ok"])
def test_llm_verdict_wins(fake_llm: FakeLLM, category: str) -> None:
    fake_llm.replies["safety"] = verdict(category, "because")
    result = safety.check("the left side of my face is drooping")
    assert (result.category, result.source, result.reason) == (category, "llm", "because")


def test_llm_overrules_loose_flag(fake_llm: FakeLLM) -> None:
    """'help me' only flags; the LLM can say it's fine."""
    fake_llm.replies["safety"] = verdict("ok")
    result = safety.check("can you help me find my next appointment")
    assert (result.category, result.source, result.flag) == ("ok", "llm", "clinical")


# --- fallback when the LLM fails ---

def test_llm_error_falls_back_to_loose_flag(fake_llm: FakeLLM) -> None:
    fake_llm.errors["safety"] = RuntimeError("groq down")
    result = safety.check("should I be worried about this result")
    assert (result.category, result.source) == ("clinical", "regex_fallback")


def test_llm_error_without_flag_is_ok(fake_llm: FakeLLM) -> None:
    fake_llm.errors["safety"] = RuntimeError("groq down")
    result = safety.check("what time is my appointment")
    assert (result.category, result.source) == ("ok", "regex_fallback")


def test_llm_timeout_falls_back(fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SAFETY_TIMEOUT_SECONDS", 0.05)
    fake_llm.delays["safety"] = 0.5
    result = safety.check("when is my follow-up at the stroke clinic")
    assert (result.category, result.source) == ("emergency", "regex_fallback")


@pytest.mark.parametrize("junk", ["not json", '{"category": "maybe"}', "{}"])
def test_llm_junk_falls_back(fake_llm: FakeLLM, junk: str) -> None:
    fake_llm.replies["safety"] = junk
    result = safety.check("is there a human I can chat with")
    assert (result.category, result.source) == ("wants_human", "regex_fallback")


# --- the ported eval cases (the real-model run is Phase 6) ---

def test_cases_file_is_well_formed() -> None:
    assert len([c for c in CASES if c["source"] == "prototype"]) == 46
    assert {c["expected"] for c in CASES} == set(safety.CATEGORIES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["text"][:40])
def test_strict_regex_agrees_with_labels(case: dict) -> None:
    """Strict rules decide alone, so they must never fire on an ok case, and when
    they fire, the category must be the human label."""
    match = safety.strict_match(case["text"])
    if match is not None:
        assert match[0] == case["expected"], f"strict rule {match[1]!r}"


def test_no_case_is_in_the_prompt() -> None:
    """Prompt examples that equal test cases would turn the eval into memorization."""
    prompt = SAFETY_PROMPT.lower()
    leaked = [c["text"] for c in CASES if c["text"].lower() in prompt]
    assert leaked == []
