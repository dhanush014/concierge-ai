"""The agent's only way to get a chat model. Tests replace `chat_model` with a fake."""

import logging
import os
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from app.agent import config
from app.agent.fake_llm import FakeChatModel
from app.db import load_env

log = logging.getLogger(__name__)

Role = Literal["safety", "agent", "summary"]
Mode = Literal["groq", "fake"]

MODELS: dict[Role, str] = {
    "safety": config.SAFETY_MODEL,
    "agent": config.AGENT_MODEL,
    "summary": config.SUMMARY_MODEL,
}
TIMEOUTS: dict[Role, float] = {
    "safety": config.SAFETY_TIMEOUT_SECONDS,
    "agent": config.AGENT_TIMEOUT_SECONDS,
    "summary": config.SUMMARY_TIMEOUT_SECONDS,
}


class FakeModeNotAllowed(RuntimeError):
    pass


def llm_mode() -> Mode:
    """'fake' only when LLM_FAKE=1 AND APP_ENV=local; LLM_FAKE=1 alone is refused, so a
    stray env var can never put a deployed API on canned answers."""
    load_env()
    if os.environ.get("LLM_FAKE") != "1":
        return "groq"
    if os.environ.get("APP_ENV") != "local":
        raise FakeModeNotAllowed("LLM_FAKE=1 is only allowed with APP_ENV=local")
    return "fake"


def check_mode_at_startup() -> Mode:
    """Called once when the API starts. Raises (so the API won't start) on a bad combo."""
    mode = llm_mode()
    if mode == "fake":
        log.warning("=" * 70)
        log.warning("FAKE LLM MODE: chat replies are canned test output, not Groq.")
        log.warning("For local end-to-end tests only (LLM_FAKE=1, APP_ENV=local).")
        log.warning("=" * 70)
    return mode


def chat_model(role: Role) -> BaseChatModel:
    """A Groq chat model for one job (or the fake in fake mode). GROQ_API_KEY comes from
    the repo .env."""
    if llm_mode() == "fake":
        return FakeChatModel(role=role)
    return ChatGroq(
        model=MODELS[role],
        temperature=0,
        timeout=TIMEOUTS[role],
        max_retries=0,  # the callers have their own fallbacks; a retry would blow the time budget
    )
