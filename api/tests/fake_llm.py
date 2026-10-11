"""A scripted stand-in for the Groq models. No network calls.

safety and summary reply with a fixed string. The agent replies with the next message
in `agent_script` (tool calls or text), then with `replies["agent"]` once the script
runs out. Any role can be told to raise or stall. Every prompt is recorded.
"""

import json
import re
import time
from collections.abc import Iterator
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult


def call(name: str, **args: Any) -> AIMessage:
    """An agent message that calls one tool."""
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"call_{name}", "type": "tool_call"}])


class FakeLLM:
    def __init__(self) -> None:
        self.replies: dict[str, str] = {
            "safety": '{"category": "ok", "reason": "fake"}',
            "agent": "Fake answer.",
            "summary": "Patient asked to talk to someone.",
            "vision": '{"payer": null, "plan_name": null, "member_name": null, "member_id": null, "group_number": null}',
        }
        self.agent_script: list[AIMessage] = []
        self.errors: dict[str, Exception] = {}
        self.delays: dict[str, float] = {}
        self.prompts: dict[str, list[list[BaseMessage]]] = {"safety": [], "agent": [], "summary": [], "vision": []}
        self.bound_tools: list[list[str]] = []  # tool names offered on each agent call

    def __call__(self, role: str) -> GenericFakeChatModel:
        if role == "agent" and self.agent_script:
            reply = self.agent_script.pop(0)
        else:
            reply = AIMessage(self.replies[role])
        return _ScriptedModel(owner=self, role=role, messages=iter([reply]))

    def calls(self, role: str) -> int:
        return len(self.prompts[role])


class _ScriptedModel(GenericFakeChatModel):
    owner: Any
    role: str
    tools_bound: bool = False

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedModel":
        self.owner.bound_tools.append([getattr(t, "name", str(t)) for t in tools])
        self.tools_bound = True
        return self

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.owner.prompts[self.role].append(messages)
        if self.role == "agent" and not self.tools_bound:
            self.owner.bound_tools.append([])  # called without tools (budget used up)
        if self.role in self.owner.delays:
            time.sleep(self.owner.delays[self.role])
        if self.role in self.owner.errors:
            raise self.owner.errors[self.role]
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        message = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs).generations[0].message
        if message.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(message.tool_calls)
            ]))
            return
        for piece in re.split(r"(\s+)", str(message.content)):
            if piece:
                chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
                if run_manager:
                    run_manager.on_llm_new_token(piece, chunk=chunk)
                yield chunk
