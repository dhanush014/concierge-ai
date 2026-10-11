"""Local embeddings (sentence-transformers). Tests replace `embed_texts` with a fake.

Documents are embedded as-is; bge's "Represent this sentence for searching relevant
passages: " prefix is for queries only (step 2).
"""

from functools import lru_cache

from app.agent.config import EMBED_DIMS, EMBED_MODEL

BATCH_SIZE = 64


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer  # slow import: only when embedding

    m = SentenceTransformer(EMBED_MODEL)
    assert m.get_embedding_dimension() == EMBED_DIMS, "EMBED_DIMS doesn't match the model"
    return m


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Unit-length vectors (cosine similarity = dot product)."""
    if not texts:
        return []
    vectors = model().encode(
        texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=len(texts) > 500
    )
    return vectors.tolist()
