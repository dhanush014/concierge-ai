"""Small, hand-made inputs for the ingestion tests: one FHIR bundle covering every event
type and edge case, and a policy doc. TODAY is fixed so the 3-year window is stable."""

import hashlib
import math
from datetime import date

TODAY = date(2026, 10, 1)  # window: 2023-10-01 .. 2026-10-01


def coded(text: str | None, display: str = "") -> dict:
    concept: dict = {"coding": [{"system": "http://snomed.info/sct", "code": "1", "display": display or text or ""}]}
    if text is not None:
        concept["text"] = text
    return concept


def obs(id_: str, category: str, name: str | None, when: str, **value) -> dict:
    return {
        "resourceType": "Observation", "id": id_,
        "category": [{"coding": [{"code": category}]}],
        "code": coded(name, display=name or "Body Weight (coding display only)"),
        "effectiveDateTime": f"{when}T09:00:00-04:00", **value,
    }


def bundle(synthea_id: str) -> dict:
    resources = [
        {"resourceType": "Patient", "id": synthea_id},
        obs("lab1", "laboratory", "Hemoglobin A1c", "2026-07-21", valueQuantity={"value": 5.95, "unit": "%"}),
        obs("bp1", "vital-signs", "Blood pressure panel", "2026-07-21", component=[
            {"code": coded("Systolic blood pressure"), "valueQuantity": {"value": 120, "unit": "mm[Hg]"}},
            {"code": coded("Diastolic blood pressure"), "valueQuantity": {"value": 80, "unit": "mm[Hg]"}},
        ]),
        obs("phq9", "survey", "Patient Health Questionnaire 9 item (PHQ-9) total score [Reported]", "2026-05-01",
            valueQuantity={"value": 4, "unit": "{score}"}),
        obs("notext", "vital-signs", None, "2026-02-02", valueQuantity={"value": 70.5, "unit": "kg"}),
        obs("old_lab", "laboratory", "Cholesterol", "2020-01-01", valueQuantity={"value": 190, "unit": "mg/dL"}),
        obs("future", "laboratory", "Glucose", "2027-01-01", valueQuantity={"value": 90, "unit": "mg/dL"}),
        {"resourceType": "Encounter", "id": "visit1", "class": {"code": "AMB"},
         "type": [coded("General examination of patient (procedure)")],
         "period": {"start": "2026-03-10T10:00:00-04:00", "end": "2026-03-10T10:30:00-04:00"},
         "participant": [{"individual": {"display": "Dr. Jane123 Doe456"}}],
         "serviceProvider": {"display": "RIVERSIDE MAIN CLINIC"},
         "reasonCode": [coded("Hypertension (disorder)")]},
        {"resourceType": "Medication", "id": "med-res-1", "code": coded("metformin 500 MG Oral Tablet")},
        {"resourceType": "MedicationRequest", "id": "med_active_old", "status": "active",
         "medicationReference": {"reference": "urn:uuid:med-res-1"}, "authoredOn": "2019-04-01T00:00:00Z",
         "dosageInstruction": [{"text": "1 tablet twice daily"}]},
        {"resourceType": "MedicationRequest", "id": "med_done_old", "status": "completed",
         "medicationCodeableConcept": coded("amoxicillin 500 MG"), "authoredOn": "2019-05-01T00:00:00Z"},
        {"resourceType": "Condition", "id": "cond_active_old", "code": coded("Diabetes mellitus type 2 (disorder)"),
         "clinicalStatus": {"coding": [{"code": "active"}]}, "onsetDateTime": "2015-06-01T00:00:00Z"},
        {"resourceType": "Condition", "id": "cond_resolved_old", "code": coded("Acute bronchitis (disorder)"),
         "clinicalStatus": {"coding": [{"code": "resolved"}]}, "onsetDateTime": "2018-02-01T00:00:00Z"},
        {"resourceType": "Condition", "id": "cond_depression", "code": coded("Major depression disorder (disorder)"),
         "clinicalStatus": {"coding": [{"code": "active"}]}, "onsetDateTime": "2025-01-15T00:00:00Z"},
        {"resourceType": "Immunization", "id": "imm1", "vaccineCode": coded("Influenza, seasonal, injectable"),
         "occurrenceDateTime": "2025-10-05T00:00:00Z"},
        {"resourceType": "AllergyIntolerance", "id": "allergy1", "code": coded("Peanut (substance)"),
         "clinicalStatus": {"coding": [{"code": "active"}]}, "recordedDate": "2010-03-03T00:00:00Z",
         "criticality": "high", "reaction": [{"manifestation": [coded("Anaphylaxis (disorder)")]}]},
        {"resourceType": "Procedure", "id": "proc1", "code": coded("Screening for drug abuse (procedure)"),
         "performedPeriod": {"start": "2026-01-05T09:00:00Z", "end": "2026-01-05T09:15:00Z"}},
        {"resourceType": "Claim", "id": "claim1", "created": "2026-03-10T00:00:00Z"},
    ]
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


# Expected chunks from bundle(): source_id -> start of the chunk text.
EXPECTED = {
    "fhir:Observation/lab1": "Lab result, 2026-07-21: Hemoglobin A1c: 5.95 %",
    "fhir:Observation/bp1": "Vital sign, 2026-07-21: Blood pressure panel: Systolic blood pressure 120 mm[Hg], Diastolic",
    "fhir:Observation/phq9": "Survey, 2026-05-01: Patient Health Questionnaire 9 item",
    "fhir:Observation/notext": "Vital sign, 2026-02-02: Body Weight (coding display only): 70.5 kg",
    "fhir:Encounter/visit1": "Visit, 2026-03-10: General examination of patient (procedure) (outpatient) at RIVERSIDE MAIN CLINIC with Dr. Jane Doe. Reason: Hypertension",
    "fhir:MedicationRequest/med_active_old": "Medication prescribed, 2019-04-01: metformin 500 MG Oral Tablet, 1 tablet twice daily, status active",
    "fhir:Condition/cond_active_old": "Condition, onset 2015-06-01: Diabetes mellitus type 2 (disorder), status active",
    "fhir:Condition/cond_depression": "Condition, onset 2025-01-15: Major depression disorder",
    "fhir:Immunization/imm1": "Immunization, 2025-10-05: Influenza, seasonal, injectable",
    "fhir:AllergyIntolerance/allergy1": "Allergy, recorded 2010-03-03: Peanut (substance), criticality high, reaction: Anaphylaxis",
    "fhir:Procedure/proc1": "Procedure, 2026-01-05: Screening for drug abuse (procedure)",
}
SENSITIVE = {"fhir:Observation/phq9", "fhir:Condition/cond_depression", "fhir:Procedure/proc1"}

POLICY_DOC = """# Parking

Intro line before any section.

## Garage rates

The first 30 minutes are free. After that, $2 per hour.

### Weekly passes

A weekly pass costs $30.

## Validation

Patients get 3 hours free with validation.

## Long section

{long}
"""


def policy_doc() -> str:
    return POLICY_DOC.format(long=" ".join(f"word{i}" for i in range(700)))


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic 384-dim unit vectors from a hash of the text. No model, no network."""
    out = []
    for t in texts:
        digest = hashlib.sha256(t.encode()).digest()
        raw = [((digest[i % 32] + i) % 97) - 48.0 for i in range(384)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        out.append([x / norm for x in raw])
    return out
