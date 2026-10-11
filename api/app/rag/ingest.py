"""Ingest policy docs and patient records into `chunks`. Run via scripts/ingest.py."""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg

from app.rag.policies import policy_chunks, policy_files
from app.rag.records import bundle_chunks, bundle_files, load_bundle, synthea_patient_id
from app.rag.store import Counts, Scope, sync

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = ROOT / "data" / "policies"
SYNTHEA_DIR = ROOT / "data" / "synthea"


def check_unique(chunks: list) -> None:
    seen: set[str] = set()
    dupes = {c.source_id for c in chunks if c.source_id in seen or seen.add(c.source_id)}
    if dupes:
        raise ValueError(f"duplicate source_id(s), e.g. two sections with the same heading: {sorted(dupes)[:3]}")


def ingest_policies(conn: psycopg.Connection, folder: Path = POLICY_DIR, namespace: str = "policy") -> Counts:
    chunks = [c for path in policy_files(folder) for c in policy_chunks(path, folder, namespace)]
    check_unique(chunks)
    return sync(conn, chunks, Scope(namespace=namespace))


@dataclass
class RecordResult:
    counts: Counts
    patients: int
    skipped_files: list[str] = field(default_factory=list)  # bundles whose patient isn't seeded


def ingest_records(conn: psycopg.Connection, folder: Path = SYNTHEA_DIR, today: date | None = None) -> RecordResult:
    """All bundles in `folder` whose patient is in the database (seeded by scripts/seed.py)."""
    today = today or date.today()
    by_synthea: dict[str, UUID] = {
        r["synthea_id"]: r["id"] for r in conn.execute("select id, synthea_id from public.patients").fetchall()
    }
    chunks, patients, skipped = [], [], []
    for path in bundle_files(folder):
        bundle = load_bundle(path)
        patient_id = by_synthea.get(synthea_patient_id(bundle))
        if patient_id is None:
            skipped.append(path.name)
            continue
        patients.append(patient_id)
        chunks.extend(bundle_chunks(bundle, patient_id, today))
    check_unique(chunks)
    return RecordResult(sync(conn, chunks, Scope(patient_ids=tuple(patients))), len(patients), skipped)
