"""Read-only tools for the chat agent.

The patient id always comes from graph state, which the chat route fills from the
login token. The LLM never supplies arguments; the router only picks which tool runs.
Each tool returns plain text in clinic time, ready to hand to the answer model.
"""

from datetime import datetime
from uuid import UUID

import psycopg

from app.agent.config import CLINIC_TZ
from app.models import Appointment, Document
from app.queries import my_appointments, my_documents

PAST_LIMIT = 5  # most recent past visits shown; the Appointments tab has the full list

KIND_LABEL = {"insurance_card": "Insurance card", "referral": "Referral"}


def clinic_time(value: datetime) -> str:
    """e.g. 'Fri, Oct 10, 2026 at 2:30 PM EDT'."""
    local = value.astimezone(CLINIC_TZ)
    return local.strftime("%a, %b %-d, %Y at %-I:%M %p %Z")


def _appointment_line(a: Appointment) -> str:
    return f"- {clinic_time(a.start_at)}: {a.visit_type} with {a.doctor_name} ({a.specialty})"


def get_my_appointments(conn: psycopg.Connection, patient_id: UUID) -> str:
    upcoming = my_appointments(conn, patient_id, "upcoming")
    past = my_appointments(conn, patient_id, "past")[:PAST_LIMIT]
    lines = ["Upcoming appointments (soonest first):"]
    lines += [_appointment_line(a) for a in upcoming] or ["- none"]
    lines.append(f"Past appointments (most recent first, up to {PAST_LIMIT}):")
    lines += [_appointment_line(a) for a in past] or ["- none"]
    return "\n".join(lines)


def _document_line(d: Document) -> str:
    uploaded = d.created_at.astimezone(CLINIC_TZ).strftime("%b %-d, %Y")
    return f"- {KIND_LABEL[d.kind]}: {d.original_filename}, uploaded {uploaded}"


def get_my_documents(conn: psycopg.Connection, patient_id: UUID) -> str:
    docs = my_documents(conn, patient_id)
    lines = ["Uploaded documents (newest first):"]
    lines += [_document_line(d) for d in docs] or ["- none"]
    return "\n".join(lines)


TOOLS = {
    "appointments": get_my_appointments,
    "documents": get_my_documents,
}
