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


# --- per-turn scores for the dashboard ---

def test_scores_for_an_answer_with_sources() -> None:
    assert tracing.turn_scores("ok", ["list_my_records"], sources=2, booked=False) == {
        "escalated": (0.0, "ok"), "tool_calls": (1.0, None), "has_sources": (1.0, None)}


def test_scores_for_an_escalation_and_a_booking() -> None:
    assert tracing.turn_scores("clinical", [], 0, False) == {"escalated": (1.0, "clinical"), "tool_calls": (0.0, None)}
    assert tracing.turn_scores("ok", ["find_open_times"], 0, True) == {
        "escalated": (0.0, "ok"), "tool_calls": (1.0, None), "booking_link": (1.0, None)}


def test_nothing_sent_without_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    sent = []
    monkeypatch.setattr(tracing._sender, "submit", lambda *a: sent.append(a))
    tracing.record_turn("abc", "ok", [], 0, False)
    assert sent == []


def test_a_langsmith_failure_never_reaches_the_chat(tracing_on, monkeypatch: pytest.MonkeyPatch) -> None:
    class Down:
        def create_feedback(self, **kwargs):
            raise ConnectionError("offline")

    monkeypatch.setattr(tracing, "_client", lambda: Down())
    tracing._send("abc", {"escalated": (0.0, "ok")})  # logs, doesn't raise
