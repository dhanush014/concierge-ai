"""Ingest RAG chunks: hospital policy docs and patient records (Synthea), embedded locally.

    uv run --project api scripts/ingest.py --only all        # or: policies | records

Re-runnable: unchanged chunks are not embedded again, chunks whose source is gone are
removed. Needs local Supabase running and the seed (patients) loaded.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))  # the `app` package

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.db import database_url  # noqa: E402
from app.rag.ingest import POLICY_DIR, SYNTHEA_DIR, ingest_policies, ingest_records  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=["policies", "records", "all"], default="all")
    args = parser.parse_args()

    with psycopg.connect(database_url(), row_factory=dict_row) as conn:  # one transaction
        if args.only in ("policies", "all"):
            start = time.monotonic()
            counts = ingest_policies(conn)
            print(f"Policies ({POLICY_DIR.name}/): {counts}  [{time.monotonic() - start:.1f}s]")
        if args.only in ("records", "all"):
            start = time.monotonic()
            result = ingest_records(conn)
            print(f"Records ({result.patients} patients): {result.counts}  [{time.monotonic() - start:.1f}s]")
            if result.skipped_files:
                print(f"  skipped {len(result.skipped_files)} bundle(s) with no seeded patient: "
                      f"{', '.join(result.skipped_files)} (run scripts/seed.py)")
    print(f"Done. Records read from {SYNTHEA_DIR.relative_to(SYNTHEA_DIR.parents[1])}/.")


if __name__ == "__main__":
    main()
