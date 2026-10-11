"""Load the local embedding and reranker models in the background at API startup, so the
first patient question that searches doesn't wait several seconds for them.

Off when RAG_WARMUP=0 (pytest, which uses fake models).
"""

import logging
import os
import threading

from app.rag import embed, rerank

log = logging.getLogger(__name__)


def warm_models_in_background() -> None:
    if os.environ.get("RAG_WARMUP", "1") == "0":
        return

    def load() -> None:
        try:
            embed.model()
            rerank.model()
            log.info("RAG models loaded")
        except Exception:  # noqa: BLE001 - a failed warm-up just means the first search loads them
            log.exception("RAG model warm-up failed")

    threading.Thread(target=load, name="rag-warmup", daemon=True).start()
