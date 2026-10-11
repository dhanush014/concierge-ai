"""Links to LangSmith traces, for the staff inbox's "View trace".

Each chat turn runs with run_id = trace_id (see routes/chat.py), so a handoff's
trace_id is the root run of the turn that started it. No LangSmith key configured
(or LangSmith unreachable) means no link, never an error.
"""

import logging
import os
from functools import lru_cache

from app.db import load_env

log = logging.getLogger(__name__)


def tracing_configured() -> bool:
    load_env()
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))


@lru_cache(maxsize=1)
def _client_and_project() -> tuple[object, str]:
    from langsmith import Client  # imported lazily: only needed when tracing is on

    client = Client()
    project = client.read_project(project_name=os.environ.get("LANGSMITH_PROJECT", "default"))
    return client, str(project.id)


@lru_cache(maxsize=512)
def trace_url(trace_id: str | None) -> str | None:
    if not trace_id or not tracing_configured():
        return None
    try:
        client, project_id = _client_and_project()
        return client.runs.get_url(trace_id, project_id=project_id, trace_id=trace_id).url  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - a missing link must not break the inbox
        log.warning("No LangSmith URL for trace %s (%s)", trace_id, type(exc).__name__)
        return None
