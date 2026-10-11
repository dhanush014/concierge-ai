"""The unit of RAG: one policy section (or part of one) or one patient record event."""

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class Chunk:
    source_id: str  # stable key, e.g. "policy:parking.md#Validation#0", "fhir:Observation/<id>"
    source_type: Literal["policy", "record"]
    doc_title: str  # policy: document title; record: event type ("Lab result")
    section: str | None  # policy: heading path; record: item name
    content: str  # what gets embedded and later quoted; self-contained
    date: date | None = None
    patient_id: UUID | None = None
    sensitive: bool = False
    payer: str | None = None
