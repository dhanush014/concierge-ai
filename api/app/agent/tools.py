"""Appointments and documents for the agent's tools, as tagged lines in clinic time.

The patient id comes from the login (toolkit.py injects it), never from the LLM.
"""

from datetime import datetime
from uuid import UUID

import psycopg

from app.agent.config import CLINIC_TZ
from app.agent.record_tools import Line, source
from app.models import Appointment, Document
from app.queries import my_appointments, my_documents

PAST_LIMIT = 5  # most recent past visits shown; the Appointments tab has the full list

KIND_LABEL = {"insurance_card": "Insurance card", "referral": "Referral"}


def clinic_time(value: datetime) -> str:
    """e.g. 'Fri, Oct 10, 2026 at 2:30 PM EDT'."""
    local = value.astimezone(CLINIC_TZ)
    return local.strftime("%a, %b %-d, %Y at %-I:%M %p %Z")


def _appointment_line(a: Appointment, when: str) -> Line:
    src = source(f"appointment:{a.id}", "appointment", "Appointment", f"{a.visit_type} with {a.doctor_name}",
                 a.start_at.astimezone(CLINIC_TZ).date())
    return src, f"{when} appointment: {clinic_time(a.start_at)}, {a.visit_type} with {a.doctor_name} ({a.specialty})"


def appointment_lines(conn: psycopg.Connection, patient_id: UUID) -> list[Line]:
    """Upcoming (soonest first), then the most recent past ones."""
    upcoming = [_appointment_line(a, "Upcoming") for a in my_appointments(conn, patient_id, "upcoming")]
    past = [_appointment_line(a, "Past") for a in my_appointments(conn, patient_id, "past")[:PAST_LIMIT]]
    return upcoming + past


def _document_line(d: Document) -> Line:
    uploaded = d.created_at.astimezone(CLINIC_TZ)
    src = source(f"document:{d.id}", "document", KIND_LABEL[d.kind], d.original_filename, uploaded.date())
    return src, f"{KIND_LABEL[d.kind]}: {d.original_filename}, uploaded {uploaded.strftime('%b %-d, %Y')}"


def document_lines(conn: psycopg.Connection, patient_id: UUID) -> list[Line]:
    """Newest first."""
    return [_document_line(d) for d in my_documents(conn, patient_id)]
