"""Hospital policy docs (markdown) -> chunks, split by heading.

Each `##`/`###` section becomes a chunk whose text starts with its heading path
("Parking > Validation"), so a chunk makes sense on its own and the heading words are
searchable. Long sections are split into ~300-word windows (~400 tokens) with ~40 words
of overlap. Text before the first `##` is the section "Overview".
"""

import re
from pathlib import Path

from app.rag.chunk import Chunk

WINDOW_WORDS = 300
OVERLAP_WORDS = 40
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def sections(markdown: str, fallback_title: str) -> tuple[str, list[tuple[str, str]]]:
    """(document title, [(heading path, body), ...]) in order; empty bodies dropped."""
    title = fallback_title
    path: list[str] = []
    out: list[tuple[str, list[str]]] = [("Overview", [])]
    for line in markdown.splitlines():
        m = HEADING.match(line)
        if not m:
            out[-1][1].append(line)
            continue
        level, text = len(m.group(1)), m.group(2)
        if level == 1:
            title = text
            continue
        path = path[: level - 2] + [text]  # ## starts a path, ### extends it
        out.append((" > ".join(path), []))
    return title, [(h, "\n".join(body).strip()) for h, body in out if "\n".join(body).strip()]


def windows(text: str) -> list[str]:
    words = text.split()
    if len(words) <= WINDOW_WORDS:
        return [text]
    out, start = [], 0
    while True:
        out.append(" ".join(words[start : start + WINDOW_WORDS]))
        if start + WINDOW_WORDS >= len(words):
            return out
        start += WINDOW_WORDS - OVERLAP_WORDS


def policy_chunks(path: Path, root: Path, namespace: str = "policy") -> list[Chunk]:
    """Chunks for one doc. source_id = "<namespace>:<file>#<heading path>#<part>"."""
    rel = path.relative_to(root).as_posix()
    title, parts = sections(path.read_text(), fallback_title=path.stem.replace("-", " ").capitalize())
    chunks = []
    for heading, body in parts:
        for i, piece in enumerate(windows(body)):
            chunks.append(
                Chunk(
                    source_id=f"{namespace}:{rel}#{heading}#{i}",
                    source_type="policy",
                    doc_title=title,
                    section=heading,
                    content=f"{title} > {heading}\n\n{piece}",
                )
            )
    return chunks


def policy_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("**/*.md"))
