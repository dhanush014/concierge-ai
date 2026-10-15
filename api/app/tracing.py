"""LangSmith: trace links for the staff inbox, and per-turn scores for monitoring.

Each chat turn runs with run_id = trace_id (see routes/chat.py), so a handoff's
trace_id is the root run of the turn that started it. After a turn, record_turn
attaches scores to that trace (escalated, tool calls, has sources, booking link); the
dashboard (scripts/langsmith_dashboard.py) charts them. No LangSmith key configured
(or LangSmith unreachable) means no link and no scores, never an error.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.db import load_env

log = logging.getLogger(__name__)


def tracing_configured() -> bool:
    load_env()
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))


@lru_cache(maxsize=1)
def _project_base_url() -> str:
    """'https://smith.langchain.com/o/<org>/projects/p/<project>': two lookups, once.
    Raises (not cached) if LangSmith can't be reached, so a later call tries again."""
    from langsmith import Client  # imported lazily: only needed when tracing is on

    client = Client()
    project = client.read_project(project_name=os.environ.get("LANGSMITH_PROJECT", "default"))
    # The SDK builds run links the same way (Client._construct_run_url); its runs.get_url
    # is async and calls the backend, which a synchronous inbox request shouldn't wait on.
    return f"{client._host_url}/o/{client._get_tenant_id()}/projects/p/{project.id}"


def trace_url(trace_id: str | None) -> str | None:
    """The LangSmith page of a chat turn. Built locally, so it works even before
    LangSmith has finished ingesting the run (the page polls until it appears)."""
    if not trace_id or not tracing_configured():
        return None
    try:
        return f"{_project_base_url()}/r/{trace_id}?poll=true"
    except Exception as exc:  # noqa: BLE001 - a missing link must not break the inbox
        log.warning("No LangSmith URL for trace %s (%s)", trace_id, type(exc).__name__)
        return None


# Scores go out on a background thread: a chat reply never waits on LangSmith.
_sender = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langsmith-feedback")

# Tools whose lines an answer cites (find_open_times returns a booking, not facts). An
# answer can rightly have none (not found, out of network): has_sources is a trend, not a pass/fail.
CITABLE_TOOLS = {"get_my_appointments", "get_my_documents", "get_lab_results", "list_my_records",
                 "search_my_records", "search_hospital_policies", "check_my_coverage"}


def turn_scores(safety: str, tools: list[str], sources: int, booked: bool) -> dict[str, tuple[float, str | None]]:
    """key -> (score, value) for one chat turn. Plain data, so it is easy to test."""
    scores: dict[str, tuple[float, str | None]] = {
        "escalated": (float(safety != "ok"), safety),
        "tool_calls": (float(len(tools)), None),
    }
    if safety == "ok" and CITABLE_TOOLS & set(tools):
        scores["has_sources"] = (float(sources > 0), None)
    if "find_open_times" in tools:
        scores["booking_link"] = (float(booked), None)
    return scores


def record_turn(trace_id: str, safety: str, tools: list[str], sources: int, booked: bool) -> None:
    if not tracing_configured():
        return
    scores = turn_scores(safety, tools, sources, booked)
    _sender.submit(_send, trace_id, scores)


def _send(trace_id: str, scores: dict[str, tuple[float, str | None]]) -> None:
    try:
        client = _client()
        for key, (score, value) in scores.items():
            client.create_feedback(run_id=trace_id, trace_id=trace_id, key=key, score=score, value=value,
                                   feedback_source_type="model")
    except Exception as exc:  # noqa: BLE001 - monitoring must never break chat
        log.warning("LangSmith scores for trace %s not sent (%s)", trace_id, type(exc).__name__)


@lru_cache(maxsize=1)
def _client():
    from langsmith import Client

    return Client()
