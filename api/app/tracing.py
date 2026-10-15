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
