"""Fake LLM mode for end-to-end tests: deterministic, free, no network.

Turned on by LLM_FAKE=1, and only allowed together with APP_ENV=local (see
llm.llm_mode). Never used by pytest, which has its own scripted fake.

  safety   always "ok", so only the real regex rules can escalate
  agent    keyword rules pick one tool call; after the result comes back it answers
           "Here is what I found." plus the tool's lines (with their source tags, so
           the answer cites them). Booking/changing gets the Appointments tab, no tool.
  summary  quotes the patient's last message
  vision   recognizes the sample cards in data/cards/ by their bytes and returns their
           truth.json fields (null for each card's expect_null fields); any other image
           reads as all nulls
"""

import base64
import hashlib
import json
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

LAB_WORDS = r"a1c|cholesterol|ldl|hdl|glucose|blood pressure|weight|bmi|hemoglobin|creatinine|lab"
RECORD_KINDS = [  # (pattern, list_my_records kind)
    (r"medication|meds|prescri|birth control", "medications"),
    (r"allerg", "allergies"),
    (r"condition|diagnos", "conditions"),
    (r"vaccin|immuniz|flu shot", "immunizations"),
]
POLICY_WORDS = r"park|fast|visiting|visitor|bill|pay|records request|telehealth|mri|ct scan|no-show"
BOOKING = r"\b(book\w*|schedule)\b"
CHANGE_VISIT = r"\b(reschedul\w*|cancel\w*|move)\b"
WHEN = r"(\d{4}-\d{2}-\d{2})(?:\D+(\d{1,2}:\d{2}))?"
COVERAGE = r"\b(cover\w*|copays?|deductible|prior auth\w*|insurance|out-of-pocket|in network)\b"
APPOINTMENTS_TAB = ("I can't reschedule or cancel visits in chat. Use the Appointments tab: "
                    "it shows your visits and makes the change right away.")
BOOKING_QUESTION = "Sure. Which doctor or kind of visit, and what day and time work for you?"


CARDS_DIR = Path(__file__).resolve().parents[3] / "data" / "cards"
CARD_FIELDS = ("payer", "plan_name", "member_name", "member_id", "group_number")


@lru_cache(maxsize=1)
def _cards_by_hash() -> dict[str, dict]:
    truth = json.loads((CARDS_DIR / "truth.json").read_text())["cards"]
    return {hashlib.sha256((CARDS_DIR / c["file"]).read_bytes()).hexdigest(): c for c in truth}


def fake_card_reading(messages: list[BaseMessage]) -> str:
    image_urls = [part["image_url"]["url"] for m in messages if isinstance(m.content, list)
                  for part in m.content if isinstance(part, dict) and part.get("type") == "image_url"]
    raw = base64.b64decode(image_urls[0].split(",", 1)[1]) if image_urls else b""
    card = _cards_by_hash().get(hashlib.sha256(raw).hexdigest(), {})
    unreadable = card.get("expect_null", [])  # what a careful reader can't see on that card
    return json.dumps({f: None if f in unreadable else card.get(f) for f in CARD_FIELDS})


def _last_human(messages: list[BaseMessage]) -> str:
    return next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def fake_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """The one tool the fake agent calls for a question, or None (answer directly)."""
    lower = text.lower()
    if re.search(CHANGE_VISIT, lower):
        return None
    if re.search(BOOKING, lower):  # "book with Dr. X on 2026-10-20 at 10:00": find it
        when = re.search(WHEN, lower)
        if when is None:
            return None
        doctor = re.search(r"\bwith (.+?)(?: on\b| at\b|$)", text, re.IGNORECASE)
        return "find_open_times", {"date": when.group(1), "time": when.group(2),
                                   "doctor": doctor.group(1).strip() if doctor else None}
    if re.search(COVERAGE, lower):
        return "check_my_coverage", {"question": text}
    if re.search(r"\bappointments?\b|\bvisits?\b", lower):
        return "get_my_appointments", {}
    if re.search(r"documents?|upload", lower):
        return "get_my_documents", {}
    if m := re.search(LAB_WORDS, lower):
        return "get_lab_results", {"test_name": m.group(0)}
    for pattern, kind in RECORD_KINDS:
        if re.search(pattern, lower):
            return "list_my_records", {"kind": kind}
    if re.search(POLICY_WORDS, lower):
        return "search_hospital_policies", {"query": text}
    return "search_my_records", {"query": text}


class FakeChatModel(BaseChatModel):
    role: str

    @property
    def _llm_type(self) -> str:
        return "concierge-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        return self  # the fake already knows the tool names

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        if self.role == "safety":
            return AIMessage(json.dumps({"category": "ok", "reason": "fake LLM mode"}))
        if self.role == "summary":
            return AIMessage(f'Patient asked: "{_last_human(messages)}"')
        if self.role == "vision":
            return AIMessage(fake_card_reading(messages))
        if isinstance(messages[-1], ToolMessage):  # tool result is in: answer from it
            results = [str(m.content).split("\n", 1)[-1] for m in messages if isinstance(m, ToolMessage)]
            return AIMessage("Here is what I found.\n" + "\n".join(results))
        question = _last_human(messages)
        call = fake_tool_call(question)
        if call is None:
            changing = re.search(CHANGE_VISIT, question.lower())
            return AIMessage(APPOINTMENTS_TAB if changing else BOOKING_QUESTION)
        name, args = call
        return AIMessage("", tool_calls=[{"name": name, "args": args, "id": "fake_call_1", "type": "tool_call"}])

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        reply = self._reply(messages)
        if reply.tool_calls:  # one chunk carrying the whole call
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": 0} for c in reply.tool_calls
            ]))
            return
        for piece in re.split(r"(\s+)", str(reply.content)):
            if piece:
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
                if run_manager:
                    run_manager.on_llm_new_token(piece, chunk=chunk)
                yield chunk
