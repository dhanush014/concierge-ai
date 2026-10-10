"""A scripted stand-in for the Groq models. No network calls.

Each role (safety, router, answer) replies with a fixed string, and can be told to
raise or to stall. Every prompt a role receives is recorded for assertions.
"""

import time
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult


class FakeLLM:
    def __init__(self) -> None:
        self.replies: dict[str, str] = {
            "safety": '{"category": "ok", "reason": "fake"}',
            "router": '{"route": "other"}',
            "answer": "Fake answer from the records.",
        }
        self.errors: dict[str, Exception] = {}
        self.delays: dict[str, float] = {}
        self.prompts: dict[str, list[list[BaseMessage]]] = {"safety": [], "router": [], "answer": []}

    def __call__(self, role: str) -> GenericFakeChatModel:
        return _ScriptedModel(owner=self, role=role, messages=iter([AIMessage(self.replies[role])]))

    def calls(self, role: str) -> int:
        return len(self.prompts[role])


class _ScriptedModel(GenericFakeChatModel):
    owner: Any
    role: str

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.owner.prompts[self.role].append(messages)
        if self.role in self.owner.delays:
            time.sleep(self.owner.delays[self.role])
        if self.role in self.owner.errors:
            raise self.owner.errors[self.role]
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
