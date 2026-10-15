"""Create (or re-create) the "Concierge AI" monitoring dashboard in LangSmith.

    uv run --project api scripts/langsmith_dashboard.py

Charts the chat turns traced to the LANGSMITH_PROJECT project (root runs named
"chat turn", see routes/chat.py) and the scores each turn gets (app/tracing.py).
Re-running replaces the dashboard, so edit CHARTS and run it again.
Uses LangSmith's custom-charts REST API with LANGSMITH_API_KEY from the repo .env.
"""

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))  # the `app` package

from app.db import load_env  # noqa: E402

TITLE = "Concierge AI: patient chat"
DESCRIPTION = ("Chat turns from the patient portal's Ask tab: volume, speed, safety escalations, "
               "tool use and Groq tokens. Built by scripts/langsmith_dashboard.py.")
TURNS = 'eq(name, "chat turn")'  # one root run per patient message
TOOLS = 'eq(run_type, "tool")'
LLM_CALLS = 'eq(run_type, "llm")'  # token counts live on the model calls, not the turn


COUNT = {"type": "count"}


def pct(field: str, p: float) -> dict:
    return {"type": "percentile", "field": field, "params": {"p": p}}


def score_avg(key: str) -> dict:
    return {"type": "avg", "field": "feedback_score", "params": {"feedback_key": key}}


def series(name: str, metric: dict, runs: str = TURNS, group_by: list[dict] | None = None) -> dict:
    """A V2 chart series over this project's runs matching `runs` (project id added in main)."""
    s = {"name": name, "metric_definition": metric,
         "filter_definition": {"source_type": "tracing_project", "run_filter": runs}}
    if group_by:
        s["group_by_definitions"] = group_by
    return s


# (title, chart type, description, series)
CHARTS = [
    ("Questions", "line", "Patient messages answered (one chat turn each).",
     [series("Questions", COUNT)]),
    ("Answer time (seconds)", "line", "From question to finished answer, including tool calls and rate-limit waits.",
     [series("Median", pct("latency_seconds", 0.5)), series("p95", pct("latency_seconds", 0.95))]),
    ("Escalation rate", "line", "Share of messages the safety check sent to a nurse (emergency, clinical or wants a person).",
     [series("Escalated", score_avg("escalated"))]),
    ("Safety verdicts", "bar", "How many messages got each safety category.",
     [series("Messages", {"type": "count", "entity": "feedback", "params": {"feedback_key": "escalated"}},
             group_by=[{"attribute": "feedback_label", "path": "escalated"}])]),
    ("Tool usage", "bar", "Which read-only tools the agent called.",
     [series("Calls", COUNT, runs=TOOLS, group_by=[{"attribute": "name"}])]),
    ("Tool calls per question", "line", "Average tool calls per message (capped at 4; 0 when escalated).",
     [series("Tool calls", score_avg("tool_calls"))]),
    ("Answers with sources", "line", "Share of record, policy and coverage answers that cite a source. "
     "Some rightly have none (not found, out of network): watch the trend.",
     [series("Has sources", score_avg("has_sources"))]),
    ("Booking links found", "line", "When the agent looked for open times, how often it found the exact time asked for.",
     [series("Exact time found", score_avg("booking_link"))]),
    ("Groq tokens", "line", "Tokens used by all model calls (safety, answers, summaries). The free tier allows "
     "about 8,000 a minute and 200,000 a day per model.",
     [series("Tokens", {"type": "sum", "field": "total_tokens"}, runs=LLM_CALLS, group_by=[{"attribute": "name"}])]),
    ("Error rate", "line", "Share of chat turns that failed (e.g. Groq rate-limited past the retries).",
     [series("Errors", {"type": "ratio", "numerator": {"type": "count", "filter": 'eq(status, "error")'},
                        "denominator": COUNT})]),
]


def main() -> None:
    load_env()
    api = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/")
    key = os.environ.get("LANGSMITH_API_KEY")
    project_name = os.environ.get("LANGSMITH_PROJECT", "default")
    assert key, "LANGSMITH_API_KEY is missing from the repo .env"
    http = httpx.Client(base_url=f"{api}/api/v1", headers={"x-api-key": key}, timeout=30)

    projects = http.get("/sessions", params={"name": project_name}).raise_for_status().json()
    assert projects, f"No LangSmith project {project_name!r} yet: send a chat message first"
    project_id = projects[0]["id"]

    for old in http.get("/charts/section", params={"title_contains": TITLE}).raise_for_status().json():
        if old["title"] == TITLE:
            http.delete(f"/charts/section/{old['id']}").raise_for_status()
            print(f"Replaced the existing dashboard ({old['id']}).")
    section = http.post("/charts/section", json={"title": TITLE, "description": DESCRIPTION}).raise_for_status().json()

    for index, (title, chart_type, description, chart_series) in enumerate(CHARTS):
        for one in chart_series:
            one["filter_definition"]["project_ids"] = [project_id]
        resp = http.post("/charts/create", json={
            "title": title, "description": description, "chart_type": chart_type, "index": index,
            "section_id": section["id"], "series": chart_series,
            "common_filters": {"session": [project_id]},  # required for workspace dashboards
        })
        if resp.is_error:
            sys.exit(f"Chart {title!r} rejected ({resp.status_code}): {resp.text[:500]}")
        print(f"  + {title}")

    web = api.replace("api.smith", "smith")
    print(f"\nDashboard {TITLE!r} with {len(CHARTS)} charts on project {project_name!r}.")
    print(f"Open LangSmith -> Dashboards, or {web}/dashboards (pick {TITLE!r}).")


if __name__ == "__main__":
    main()
