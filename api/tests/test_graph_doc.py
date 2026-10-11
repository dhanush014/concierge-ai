"""docs/agent-graph.md must match the graph (regenerate: uv run python -m app.agent.draw)."""

from app.agent.draw import DOC, render


def test_graph_doc_is_up_to_date() -> None:
    assert DOC.exists(), "run: cd api && uv run python -m app.agent.draw"
    assert DOC.read_text() == render(), "graph changed: run `cd api && uv run python -m app.agent.draw`"
