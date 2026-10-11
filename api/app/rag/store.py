"""Write chunks to the `chunks` table, embedding only what changed.

content_hash = sha256(embed model + content). Per chunk (by source_id):
  new        not in the table yet           -> embed + insert
  changed    hash differs                   -> embed + update
  unchanged  same hash (metadata refreshed if e.g. a sensitive rule changed, no embedding)
  removed    in the table, in this run's scope, but no longer produced -> delete
The scope keeps one run from deleting another's chunks: a policy namespace, or the
patients being ingested.
"""

import hashlib
from dataclasses import dataclass, field
from uuid import UUID

import psycopg

from app.agent.config import EMBED_MODEL
from app.rag import embed
from app.rag.chunk import Chunk

META = ("source_type", "patient_id", "payer", "doc_title", "section", "date", "sensitive")


@dataclass
class Counts:
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: int = 0
    embedded: int = field(default=0)

    def __str__(self) -> str:
        return (f"{self.new} new, {self.changed} changed, {self.unchanged} unchanged, "
                f"{self.removed} removed ({self.embedded} embedded)")


@dataclass(frozen=True)
class Scope:
    """Which existing rows this run owns: a doc namespace (policies or contracts), or
    these patients' records."""

    namespace: str | None = None  # docs: source_id starts with "<namespace>:"
    patient_ids: tuple[UUID, ...] = ()  # records
    source_type: str = "policy"  # what the namespace holds: "policy" or "contract"

    def where(self) -> tuple[str, tuple]:
        if self.namespace is not None:
            return "source_type = %s and source_id like %s", (self.source_type, f"{self.namespace}:%")
        return "source_type = 'record' and patient_id = any(%s)", (list(self.patient_ids),)


def content_hash(content: str) -> str:
    return hashlib.sha256(f"{EMBED_MODEL}\n{content}".encode()).hexdigest()


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def sync(conn: psycopg.Connection, chunks: list[Chunk], scope: Scope) -> Counts:
    """Make the table match `chunks` within `scope`. One transaction (the caller's)."""
    where, params = scope.where()
    existing = {
        r["source_id"]: r
        for r in conn.execute(
            f"select source_id, content_hash, {', '.join(META)} from public.chunks where {where}", params
        ).fetchall()
    }
    counts = Counts()
    to_embed: list[tuple[Chunk, str]] = []
    meta_updates = []
    for c in chunks:
        h = content_hash(c.content)
        old = existing.get(c.source_id)
        if old is None:
            counts.new += 1
            to_embed.append((c, h))
        elif old["content_hash"] != h:
            counts.changed += 1
            to_embed.append((c, h))
        else:
            counts.unchanged += 1
            if any(old[k] != getattr(c, k) for k in META):
                meta_updates.append((*(getattr(c, k) for k in META), c.source_id))

    vectors = embed.embed_texts([c.content for c, _ in to_embed])
    counts.embedded = len(vectors)
    with conn.cursor() as cur:
        cur.executemany(
            f"insert into public.chunks (source_id, content, content_hash, embedding, {', '.join(META)})"
            f" values (%s, %s, %s, %s::extensions.vector, {', '.join(['%s'] * len(META))})"
            " on conflict (source_id) do update set content = excluded.content,"
            " content_hash = excluded.content_hash, embedding = excluded.embedding,"
            + ", ".join(f" {k} = excluded.{k}" for k in META),
            [
                (c.source_id, c.content, h, vector_literal(v), *(getattr(c, k) for k in META))
                for (c, h), v in zip(to_embed, vectors, strict=True)
            ],
        )
        if meta_updates:
            cur.executemany(
                f"update public.chunks set {', '.join(f'{k} = %s' for k in META)} where source_id = %s",
                meta_updates,
            )

    gone = sorted(set(existing) - {c.source_id for c in chunks})
    if gone:
        conn.execute("delete from public.chunks where source_id = any(%s)", (gone,))
    counts.removed = len(gone)
    return counts
