"""Cross-encoder reranker (BAAI/bge-reranker-base, local). Tests replace `score`."""

from functools import lru_cache

from app.agent.config import RERANK_MODEL


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import CrossEncoder  # slow import: only when reranking

    return CrossEncoder(RERANK_MODEL)


def score(question: str, texts: list[str]) -> list[float]:
    """Relevance of each text to the question; higher is better (raw logits)."""
    if not texts:
        return []
    return [float(s) for s in model().predict([(question, t) for t in texts])]
