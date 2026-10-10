"""Safety check: runs first on every chat message.

Cascade, ported from the old prototype (guardrail.py):
1. Strict regex. A match decides immediately, no LLM call.
2. Loose regex flags the message, then the LLM decides (its verdict wins either way).
3. If the LLM errors, times out or returns junk, the loose-regex flag decides.

Categories, most cautious first: emergency > clinical > wants_human > ok.
"""

import contextvars
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import config, llm
from app.agent.safety_prompt import SAFETY_PROMPT

log = logging.getLogger(__name__)

Category = Literal["emergency", "clinical", "wants_human", "ok"]
Source = Literal["regex", "llm", "regex_fallback"]
CATEGORIES: tuple[Category, ...] = ("emergency", "clinical", "wants_human", "ok")
ESCALATING: tuple[Category, ...] = ("emergency", "clinical", "wants_human")

# STRICT: vocabulary unlikely to show up in an administrative sentence, so a match
# decides on its own. Port of the old HIGH_CONFIDENCE rules (B, C, D, E -> clinical),
# plus the life-threatening ones split out as emergency and the new wants_human.
STRICT: dict[Category, list[str]] = {
    "emergency": [
        r"\bchest (pain|pains|pressure|tightness)\b",
        r"\bmy chest (feels|is) (tight|heavy)\b",
        r"\b(can'?t|cannot|trouble|hard to|difficulty) breath(e|ing)\b",
        r"\bshort(ness)? of breath\b",
        r"\b(i'?m|i am|is|he'?s|she'?s) having an? (heart attack|stroke|seizure)\b",
        r"\boverdos(ed|ing)\b",
        r"\b(fainted|passed out|unconscious)\b",
        r"\b(kill|hurt|harm|cut) myself\b",
        r"\b(suicide|suicidal|end my life|want to die)\b",
        r"\b(this is|it'?s|having) an emergency\b",
    ],
    "clinical": [
        r"\bi\s?(have|'ve had|am having|'m having)\b[\w\s]{0,20}\b(pain|ache|fever|rash|swelling)\b",
        r"\b(it|my [\w\s]{1,20})\b \bhurts\b",
        r"\b(dizzy|nauseous|bleeding|vomiting)\b",
        r"\bsymptoms?\b",
        r"can i \b(stop|skip|double|change)\b [\w\s]{0,20} \b(taking|my medication|my dose)\b",
        r"\b(urgent|urgently)\b",
        r"need to \b(come in|be seen)\b \b(sooner|today|now)\b",
        r"\b(scared|frightened|terrified|panicking)\b",
    ],
    "wants_human": [
        r"\b(talk|speak|chat)\b (to|with) (a |an |the |some )?(real |actual |live )?"
        r"(person|human|nurse|someone|somebody|representative|staff)\b",
        r"\b(real|actual|live) (person|human)\b",
        r"\b(transfer|connect) me\b",
    ],
}

# LOOSE: generic words ("normal", "mean", "worried", "help me") that also appear in
# benign sentences. They only flag; the LLM can overrule. Port of LOW_CONFIDENCE.
# "help me" moved here from the old strict list: "can you help me find my appointment"
# is not clinical.
LOOSE: dict[Category, list[str]] = {
    # Bare words: "stroke clinic", "seizure medication" are appointments, not emergencies.
    "emergency": [r"\b(heart attack|stroke|seizure|overdose)\b"],
    "clinical": [
        r"is \b(this|that|it|my [\w\s]{1,30})\b \b(normal|high|low|bad|concerning|okay|ok|fine|healthy|dangerous)\b",
        r"\b(what|how)\b \b(does|do)\b \b(this|that|it|my [\w\s]{1,30})\b \bmean\b",
        r"should i (be )?\b(worried|concerned)\b",
        r"am i \b(ok|okay|fine|healthy)\b",
        r"is \b(this|that|my [\w\s]{1,30})\b (a )?\b(problem|issue)\b",
        r"why \b(is|are|does|did)\b my [\w\s]{1,30} \b(high|low|up|down|changing|different)\b",
        r"\bi\s?(feel|felt|am feeling|'m feeling|have been feeling|'ve been feeling|been feeling)\b",
        r"\b(getting|feeling|been)\b \bworse\b",
        r"what should i \b(do|take)\b",
        r"\b(do|should)\b i need to \b(see|visit|call)\b",
        r"should i \b(take|stop|start|continue)\b",
        r"is it \b(safe|okay|ok)\b to",
        r"\b(can'?t|cannot)\b wait",
        r"\b(severe|severely)\b",
        r"\b(right now|as soon as possible|asap)\b",
        r"\b(worried|anxious|nervous)\b about",
        r"\bi'?m\b (really |very )?\b(worried|scared|anxious)\b",
        r"\bhelp me\b",
    ],
    "wants_human": [
        r"\b(someone|somebody|a person|a human)\b",
        r"\bcall me\b",
    ],
}


def _compile(rules: dict[Category, list[str]]) -> list[tuple[Category, str, re.Pattern[str]]]:
    return [(cat, p, re.compile(p)) for cat in ESCALATING for p in rules.get(cat, [])]


_STRICT = _compile(STRICT)
_LOOSE = _compile(LOOSE)
_executor = ThreadPoolExecutor(max_workers=4)


@dataclass(frozen=True)
class SafetyResult:
    category: Category
    source: Source
    reason: str | None  # matched pattern (regex) or the model's reason (llm)
    flag: Category | None = None  # loose-regex flag, kept for tracing either way


def first_match(rules: list[tuple[Category, str, re.Pattern[str]]], text: str) -> tuple[Category, str] | None:
    lower = text.lower().replace("\u2019", "'")  # phones type curly apostrophes
    for category, pattern, compiled in rules:
        if compiled.search(lower):
            return category, pattern
    return None


def strict_match(text: str) -> tuple[Category, str] | None:
    """The strict-regex verdict alone (used by the eval cases)."""
    return first_match(_STRICT, text)


def _parse(content: str) -> tuple[Category, str]:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    data = json.loads(match.group(0) if match else content)
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    return category, str(data.get("reason", ""))


def classify(text: str) -> tuple[Category, str]:
    """One LLM verdict. Raises on any failure; the cascade handles that."""
    model = llm.chat_model("safety").bind(response_format={"type": "json_object"})
    reply = model.invoke([SystemMessage(SAFETY_PROMPT), HumanMessage(text)])
    return _parse(str(reply.content))


def check(text: str) -> SafetyResult:
    strict = first_match(_STRICT, text)
    if strict:
        return SafetyResult(category=strict[0], source="regex", reason=strict[1])

    loose = first_match(_LOOSE, text)
    flag = loose[0] if loose else None

    # copy_context so the LLM call stays inside the current trace (LangSmith nests
    # runs through contextvars, which a plain thread would drop).
    future = _executor.submit(contextvars.copy_context().run, classify, text)
    try:
        category, reason = future.result(timeout=config.SAFETY_TIMEOUT_SECONDS)
        return SafetyResult(category=category, source="llm", reason=reason, flag=flag)
    except Exception as exc:  # any failure, timeout included, falls back to the flag
        log.warning("Safety LLM failed (%s); using the regex flag %s", type(exc).__name__, flag)
        return SafetyResult(
            category=flag or "ok",
            source="regex_fallback",
            reason=loose[1] if loose else None,
            flag=flag,
        )
