"""The agent's only way to get a chat model. Tests replace `chat_model` with a fake."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from app.agent import config
from app.db import load_env

Role = Literal["safety", "router", "answer"]

MODELS: dict[Role, str] = {
    "safety": config.SAFETY_MODEL,
    "router": config.ROUTER_MODEL,
    "answer": config.ANSWER_MODEL,
}
TIMEOUTS: dict[Role, float] = {
    "safety": config.SAFETY_TIMEOUT_SECONDS,
    "router": config.ROUTER_TIMEOUT_SECONDS,
    "answer": config.ANSWER_TIMEOUT_SECONDS,
}


def chat_model(role: Role) -> BaseChatModel:
    """A Groq chat model for one job. GROQ_API_KEY comes from the repo .env."""
    load_env()
    return ChatGroq(
        model=MODELS[role],
        temperature=0,
        timeout=TIMEOUTS[role],
        max_retries=0,  # the callers have their own fallbacks; a retry would blow the time budget
    )
