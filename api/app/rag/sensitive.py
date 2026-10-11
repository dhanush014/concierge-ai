"""Which record chunks are sensitive (mental health, substance use, abuse/violence).

Retrieval in step 2 excludes them, so the assistant never brings them up. Ported from
the prototype's chunk.py (SENSITIVE_KEYWORDS + SENSITIVE_OBSERVATION_KEYWORDS), which
only caught the screening questionnaires; widened to the diagnoses and procedures too.
Matching is on lowercase substrings of the item name (and any reason text).
"""

# Screening questionnaires and their scores (Observations, Procedures).
SCREENS = (
    "phq-2", "phq-9", "patient health questionnaire",  # depression
    "gad-7", "generalized anxiety disorder",  # anxiety
    "audit-c", "alcohol use disorders identification",  # alcohol
    "dast-10", "drug abuse screening",  # drugs
    "hark", "humiliation, afraid, rape", "intimate partner",  # abuse
    "prapare",  # social risk (includes safety and stress questions)
)

# Conditions, procedures and visit reasons.
TOPICS = (
    "depress", "anxiety", "panic", "bipolar", "schizophren", "psychos", "ptsd",
    "post-traumatic", "mental", "psychiatric", "suicid", "self-harm", "self harm",
    "eating disorder", "anorexia", "bulimia",
    # Not bare "substance": SNOMED tags every allergen "(substance)", e.g. "Peanut (substance)".
    "substance use", "substance abuse", "substance misuse", "alcohol", "drug abuse", "drug use",
    "drug dependence", "opioid",
    "overdose", "addiction", "dependence", "misuse", "withdrawal",
    "abuse", "violence", "assault", "stress",
)


def is_sensitive(*texts: str | None) -> bool:
    lower = " ".join(t for t in texts if t).lower()
    return any(k in lower for k in SCREENS) or any(k in lower for k in TOPICS)
