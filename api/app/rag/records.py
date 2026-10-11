"""Synthea FHIR bundles -> one chunk per clinical event, last 3 years.

Ported from the prototype's scratch/chunk.py (Observations, Conditions, Medication
requests) and extended to visits, immunizations, allergies and procedures. Fallbacks
from scratch/flag_hazards.py's findings: some codes have no `text` (use the first
coding's display), and each resource type keeps its date in a different field.

Each chunk's text names the event type and date, so it reads on its own:
"Lab result, 2026-07-21: Hemoglobin A1c/Hemoglobin.total in Blood: 5.95 %".
Ongoing items (an active condition, allergy or medication) are kept even when they
started more than 3 years ago: "what am I allergic to" must still find a 2015 allergy.

Skipped on purpose: claims and benefit statements (billing), diagnostic reports and
document references (mostly repeat the lab values), care plans, devices, supplies.
"""

import json
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from app.rag.chunk import Chunk
from app.rag.sensitive import is_sensitive

YEARS_BACK = 3
SKIP_FILE_PREFIXES = ("hospitalInformation", "practitionerInformation")

OBSERVATION_LABEL = {
    "laboratory": "Lab result",
    "vital-signs": "Vital sign",
    "survey": "Survey",
    "social-history": "Social history",
    "exam": "Exam finding",
    "imaging": "Imaging result",
    "procedure": "Procedure result",
}


# Encounter.class codes -> words.
SETTING = {"AMB": "outpatient", "EMER": "emergency", "IMP": "inpatient", "VR": "telehealth", "HH": "home visit",
           "OBSENC": "observation", "ACUTE": "inpatient", "SS": "same day", "wellness": "wellness", "ambulatory": "outpatient",
           "emergency": "emergency", "inpatient": "inpatient", "urgentcare": "urgent care", "virtual": "telehealth"}


# What the date means, where it isn't the day the event happened.
DATE_WORD = {"Condition": "onset ", "Allergy": "recorded "}


def plain_name(name: str) -> str:
    """Synthea appends digits to names ("Dr. Bella510 Kutch271")."""
    return re.sub(r"(?<=[A-Za-z])\d+", "", name)


def is_ongoing(r: dict) -> bool:
    """An active condition or allergy, or an active prescription."""
    if r.get("resourceType") == "MedicationRequest":
        return r.get("status") == "active"
    codes = [c.get("code") for c in (r.get("clinicalStatus") or {}).get("coding", [])]
    return "active" in codes


def cutoff(today: date) -> date:
    try:
        return today.replace(year=today.year - YEARS_BACK)
    except ValueError:  # Feb 29
        return today.replace(year=today.year - YEARS_BACK, day=28)


def code_name(concept: dict[str, Any] | None) -> str:
    """concept.text, else the first coding's display (flag_hazards: text is sometimes missing)."""
    concept = concept or {}
    if concept.get("text"):
        return str(concept["text"])
    codings = concept.get("coding") or [{}]
    return str(codings[0].get("display", "")).strip()


def first_date(r: dict[str, Any], *fields: str) -> date | None:
    """The first of `fields` that holds a date; periods use their start."""
    for f in fields:
        value = r.get(f)
        if isinstance(value, dict):
            value = value.get("start")
        if isinstance(value, str) and len(value) >= 10:
            return date.fromisoformat(value[:10])
    return None


def quantity(q: dict[str, Any]) -> str:
    value = q.get("value")
    if isinstance(value, float):
        value = round(value, 2)
    return f"{value} {q.get('unit', '')}".strip()


def observation_value(r: dict[str, Any]) -> str | None:
    if "valueQuantity" in r:
        return quantity(r["valueQuantity"])
    if "valueCodeableConcept" in r:
        return code_name(r["valueCodeableConcept"])
    if "valueString" in r:
        return str(r["valueString"])
    if "component" in r:  # panels, e.g. blood pressure: "Systolic 120 mm[Hg], Diastolic 80 mm[Hg]"
        parts = []
        for c in r["component"]:
            value = quantity(c["valueQuantity"]) if "valueQuantity" in c else code_name(c.get("valueCodeableConcept"))
            parts.append(f"{code_name(c.get('code'))} {value}".strip())
        return ", ".join(parts)
    return None


def _observation(r: dict[str, Any]) -> tuple[str, str, str, date | None] | None:
    name, value = code_name(r.get("code")), observation_value(r)
    if not name or value is None:
        return None
    category = code_name((r.get("category") or [{}])[0]) or ""
    codes = [c.get("code") for cat in r.get("category", []) for c in cat.get("coding", [])]
    label = next((OBSERVATION_LABEL[c] for c in codes if c in OBSERVATION_LABEL), category or "Observation")
    return label, name, f"{name}: {value}", first_date(r, "effectiveDateTime", "effectivePeriod", "issued")


def _encounter(r: dict[str, Any]) -> tuple[str, str, str, date | None]:
    kind = code_name((r.get("type") or [{}])[0]) or "Visit"
    code = (r.get("class") or {}).get("code", "")
    setting = SETTING.get(code, code)
    text = kind + (f" ({setting})" if setting else "")
    where = (r.get("serviceProvider") or {}).get("display")
    who = next((p.get("individual", {}).get("display") for p in r.get("participant", []) if p.get("individual")), None)
    who = plain_name(who) if who else None
    reason = code_name((r.get("reasonCode") or [{}])[0])
    if where:
        text += f" at {where}"
    if who:
        text += f" with {who}"
    if reason:
        text += f". Reason: {reason}"
    return "Visit", kind, text, first_date(r, "period")


def _medication(r: dict[str, Any], meds: dict[str, dict[str, Any]]) -> tuple[str, str, str, date | None]:
    if "medicationCodeableConcept" in r:
        name = code_name(r["medicationCodeableConcept"])
    else:  # a reference to a Medication resource in the same bundle
        ref = (r.get("medicationReference") or {}).get("reference", "")
        name = code_name(meds.get(ref.removeprefix("urn:uuid:"), {}).get("code"))
    dosage = (r.get("dosageInstruction") or [{}])[0].get("text", "")
    text = name + (f", {dosage}" if dosage else "") + f", status {r.get('status', 'unknown')}"
    return "Medication prescribed", name, text, first_date(r, "authoredOn")


def _condition(r: dict[str, Any]) -> tuple[str, str, str, date | None]:
    name = code_name(r.get("code"))
    status = code_name(r.get("clinicalStatus")) or (r.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "")
    text = f"{name}, status {status}" if status else name
    return "Condition", name, text, first_date(r, "onsetDateTime", "onsetPeriod", "recordedDate")


def _simple(label: str, *date_fields: str):
    def build(r: dict[str, Any]) -> tuple[str, str, str, date | None]:
        name = code_name(r.get("vaccineCode") or r.get("code"))
        text = name
        if label == "Allergy":
            if r.get("criticality"):
                text += f", criticality {r['criticality']}"
            reactions = [code_name(m) for rx in r.get("reaction", []) for m in rx.get("manifestation", [])]
            if reactions:
                text += f", reaction: {', '.join(reactions)}"
        return label, name, text, first_date(r, *date_fields)

    return build


BUILDERS = {
    "Observation": _observation,
    "Encounter": _encounter,
    "Condition": _condition,
    "Immunization": _simple("Immunization", "occurrenceDateTime"),
    "AllergyIntolerance": _simple("Allergy", "recordedDate", "onsetDateTime"),
    "Procedure": _simple("Procedure", "performedDateTime", "performedPeriod"),
}


def bundle_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.json") if not p.name.startswith(SKIP_FILE_PREFIXES))


def bundle_chunks(bundle: dict[str, Any], patient_id: UUID, today: date) -> Iterator[Chunk]:
    """Chunks for one patient's bundle, events from the last 3 years only."""
    since = cutoff(today)
    resources = [e.get("resource", {}) for e in bundle.get("entry", [])]
    meds = {r["id"]: r for r in resources if r.get("resourceType") == "Medication"}
    for r in resources:
        rtype = r.get("resourceType")
        if rtype == "MedicationRequest":
            built = _medication(r, meds)
        elif rtype in BUILDERS:
            built = BUILDERS[rtype](r)
        else:
            continue
        if built is None:
            continue
        label, name, text, when = built
        if not name or when is None or when > today:
            continue
        if when < since and not is_ongoing(r):
            continue
        reason = code_name((r.get("reasonCode") or [{}])[0])
        yield Chunk(
            source_id=f"fhir:{rtype}/{r['id']}",
            source_type="record",
            doc_title=label,
            section=name,
            content=f"{label}, {DATE_WORD.get(label, '')}{when.isoformat()}: {text}",
            date=when,
            patient_id=patient_id,
            sensitive=is_sensitive(name, text, reason),
        )


def synthea_patient_id(bundle: dict[str, Any]) -> str:
    return next(e["resource"]["id"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Patient")


def load_bundle(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
