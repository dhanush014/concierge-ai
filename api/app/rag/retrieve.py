"""Retrieval: question -> the most relevant chunks the caller may see.

1. Embed the question (bge query prefix).
2. Exact vector search with filters applied first: this patient's records and/or the
   policy docs, never sensitive. ~100-300 rows, compared in well under a millisecond,
   so there's no index to starve the filters (see migration 0009).
3. Rerank the top RETRIEVE_CANDIDATES with a cross-encoder, keep the top N by score,
   across records and policies alike.
4. Order for display: records newest first, then policies by score.

The patient id comes from the caller (the login token), never from the question.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

import psycopg

from app.agent.config import RETRIEVE_CANDIDATES, RETRIEVE_TOP_N
from app.rag import embed, rerank
from app.rag.store import vector_literal

Scope = Literal["records", "policies", "both"]

SCOPE_SQL: dict[Scope, str] = {
    "records": "source_type = 'record' and patient_id = %(patient)s",
    "policies": "source_type = 'policy'",
    "both": "((source_type = 'record' and patient_id = %(patient)s) or source_type = 'policy')",
}


@dataclass(frozen=True)
class Retrieved:
    source_id: str
    source_type: Literal["policy", "record"]
    doc_title: str
    section: str | None
    date: date | None
    content: str
    similarity: float  # cosine similarity of question and chunk
    rerank_score: float | None  # None when reranking is off


def candidates(conn: psycopg.Connection, question: str, patient_id: UUID | None, scope: Scope, limit: int) -> list[Retrieved]:
    """Nearest chunks by cosine similarity, filters applied first."""
    if scope != "policies" and patient_id is None:
        raise ValueError("records need a patient_id")
    rows = conn.execute(
        "select source_id, source_type, doc_title, section, date, content,"
        " 1 - (embedding <=> %(q)s::extensions.vector) as similarity"
        f" from public.chunks where {SCOPE_SQL[scope]} and not sensitive"
        " order by embedding <=> %(q)s::extensions.vector, source_id limit %(limit)s",
        {"q": vector_literal(embed.embed_query(question)), "patient": patient_id, "limit": limit},
    ).fetchall()
    return [Retrieved(**r, rerank_score=None) for r in rows]


def display_order(chunks: list[Retrieved]) -> list[Retrieved]:
    """Records newest first, then policies in the order given (best first)."""
    records = sorted((c for c in chunks if c.source_type == "record"), key=lambda c: c.date or date.min, reverse=True)
    return records + [c for c in chunks if c.source_type == "policy"]


def ranked(
    conn: psycopg.Connection,
    question: str,
    patient_id: UUID | None,
    scope: Scope = "both",
    top_n: int = RETRIEVE_TOP_N,
    use_reranker: bool = True,
) -> list[Retrieved]:
    """The top N by relevance (reranker score, or similarity without it), best first."""
    found = candidates(conn, question, patient_id, scope, RETRIEVE_CANDIDATES)
    if not use_reranker:
        return found[:top_n]
    scores = rerank.score(question, [c.content for c in found])
    rescored = [Retrieved(**{**c.__dict__, "rerank_score": s}) for c, s in zip(found, scores, strict=True)]
    return sorted(rescored, key=lambda c: c.rerank_score, reverse=True)[:top_n]


def retrieve(
    conn: psycopg.Connection,
    question: str,
    patient_id: UUID | None,
    scope: Scope = "both",
    top_n: int = RETRIEVE_TOP_N,
    use_reranker: bool = True,
) -> list[Retrieved]:
    """The top N chunks for the question, ready to show: records newest first."""
    return display_order(ranked(conn, question, patient_id, scope, top_n, use_reranker))
