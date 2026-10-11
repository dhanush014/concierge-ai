"""In-network check and name check: plain code, never the LLM.

Payer names are compared after normalizing (case, spaces, punctuation) against the
payer and its aliases in data/payers.json, then looked up in network_contracts.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import psycopg

PAYERS_FILE = Path(__file__).resolve().parents[3] / "data" / "payers.json"

NetworkStatus = Literal["in_network", "out_of_network", "not_on_file"]


def norm(text: str | None) -> str:
    """'  RIVERBEND  Health, Inc. ' -> 'riverbend health inc'."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


@lru_cache(maxsize=1)
def payer_names() -> dict[str, str]:
    """Normalized payer name or alias -> canonical payer name."""
    names: dict[str, str] = {}
    for p in json.loads(PAYERS_FILE.read_text())["payers"]:
        for name in (p["payer"], *p.get("aliases", [])):
            names[norm(name)] = p["payer"]
    return names


@dataclass(frozen=True)
class NetworkMatch:
    status: NetworkStatus
    payer: str | None  # the canonical payer we matched, if any


def match_network(conn: psycopg.Connection, payer: str | None, plan_name: str | None) -> NetworkMatch:
    canonical = payer_names().get(norm(payer))
    if canonical is None:
        return NetworkMatch("not_on_file", None)
    rows = conn.execute(
        "select plan_name, in_network from public.network_contracts where payer = %s", (canonical,)
    ).fetchall()
    if not rows:
        return NetworkMatch("not_on_file", canonical)
    same_plan = [r for r in rows if plan_name and norm(r["plan_name"]) == norm(plan_name)]
    decided = same_plan or rows
    if len({r["in_network"] for r in decided}) != 1:  # plans of this payer disagree, plan unknown
        return NetworkMatch("not_on_file", canonical)
    return NetworkMatch("in_network" if decided[0]["in_network"] else "out_of_network", canonical)


def name_matches(card_name: str | None, first_name: str, last_name: str) -> bool:
    """Same person, ignoring case, punctuation, order and extra names: "CASPER, AJA M" matches."""
    words = set(norm(card_name).split())
    return {norm(first_name), norm(last_name)} <= words


def name_warning(card_name: str | None, first_name: str, last_name: str) -> str | None:
    if not card_name or name_matches(card_name, first_name, last_name):
        return None
    return (f"The name on this card ({card_name}) doesn't match your name ({first_name} {last_name}). "
            "Check that it's your card before confirming.")
