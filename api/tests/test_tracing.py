"""LangSmith trace links for the staff inbox: built locally, never an error."""

import pytest

from app import tracing


@pytest.fixture
def tracing_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_not_a_real_key")


def test_link_points_at_the_turns_trace(tracing_on, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "_project_base_url", lambda: "https://smith.example/o/org/projects/p/proj")
    assert tracing.trace_url("abc-123") == "https://smith.example/o/org/projects/p/proj/r/abc-123?poll=true"


def test_no_link_when_langsmith_is_unreachable(tracing_on, monkeypatch: pytest.MonkeyPatch) -> None:
    def down() -> str:
        raise ConnectionError("offline")

    monkeypatch.setattr(tracing, "_project_base_url", down)
    assert tracing.trace_url("abc-123") is None


def test_no_link_without_tracing_or_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    assert tracing.trace_url("abc-123") is None
    assert tracing.trace_url(None) is None
