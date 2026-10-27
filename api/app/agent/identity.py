"""Is the patient asking about another patient by name? Checked in code before the agent
model runs, so a request for "Bart Brekke's labs" never reaches the tools: asked that,
the model has shown the signed-in patient's own results under the other name, or read
a misspelled name ("barts brekke") as a lab test.

A name counts when the other patient's last name appears (or their first and last
name together, for last names that are everyday words), allowing a possessive, a
trailing s and one typo in names of 5+ letters ("Brecke", "Breke"). A first name alone
is left to the prompt rule: first names like "Len" or "Manual" are everyday words.
"""

import re
from uuid import UUID

import psycopg

COMMON_WORD_LAST_NAMES = {"hand", "bins"}  # need the first name too


def _words(text: str) -> set[str]:
    words = set()
    for w in re.findall(r"[a-z]+", text.lower().replace("’", "'").replace("'s", "")):
        words.add(w)
        if w.endswith("s") and len(w) > 3:
            words.add(w[:-1])  # "barts" -> "bart"
    return words


def _one_edit(a: str, b: str) -> bool:
    """At most one inserted, deleted or changed letter."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _mentions(words: set[str], name: str) -> bool:
    name = name.lower()
    return name in words or (len(name) >= 5 and any(_one_edit(w, name) for w in words))


def other_patient_named(conn: psycopg.Connection, text: str, patient_id: UUID | str) -> str | None:
    """The full name of another patient the message names, or None."""
    words = _words(text)
    rows = conn.execute(
        "select first_name, last_name from public.patients where id <> %s", (patient_id,)
    ).fetchall()
    for r in rows:
        if not (r["first_name"].isalpha() and r["last_name"].isalpha()):
            continue  # test fixtures ("Test Patient3"), not real names
        last = _mentions(words, r["last_name"])
        if last and (r["last_name"].lower() not in COMMON_WORD_LAST_NAMES or _mentions(words, r["first_name"])):
            return f"{r['first_name']} {r['last_name']}"
    return None
