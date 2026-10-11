"""Fake LLM mode for end-to-end tests: deterministic, free, no network.

Turned on by LLM_FAKE=1, and only allowed together with APP_ENV=local (see
llm.llm_mode). Never used by pytest, which has its own scripted fake.

  safety  always "ok", so only the real regex rules can escalate
  router  keyword rules
  answer  repeats the tool's records back, streamed word by word
"""

import json
import re
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

ROUTER_KEYWORDS = [  # first match wins
    ("change_appointment", r"\b(book|reschedul\w*|cancel\w*|move)\b"),
    ("documents", r"\b(documents?|upload\w*|insurance card|referral)\b"),
    ("appointments", r"\b(appointments?|visits?)\b"),
]
RECORDS_MARKER = "Records:\n"


def _last_human(messages: list[BaseMessage]) -> str:
    return next((str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def fake_route(text: str) -> str:
    lower = text.lower()
    return next((route for route, pattern in ROUTER_KEYWORDS if re.search(pattern, lower)), "other")


class FakeChatModel(BaseChatModel):
    role: str

    @property
    def _llm_type(self) -> str:
        return "concierge-fake"

    def _reply(self, messages: list[BaseMessage]) -> str:
        if self.role == "safety":
            return json.dumps({"category": "ok", "reason": "fake LLM mode"})
        if self.role == "router":
            return json.dumps({"route": fake_route(_last_human(messages))})
        system = str(messages[0].content)
        records = system.split(RECORDS_MARKER, 1)[-1].strip()
        return f"Here is what I found.\n{records}"

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self._reply(messages)))])

    def _stream(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        for piece in re.split(r"(\s+)", self._reply(messages)):
            if not piece:
                continue
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk
