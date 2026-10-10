"""Read queries shared by the HTTP routes and the chat agent's tools.

Both callers pass the patient id from the login token, so these never decide whose
data to read.
"""

from typing import Literal
from uuid import UUID

import psycopg

from app.models import Appointment, Document

APPOINTMENT_SELECT = """
    select a.id, a.status, a.created_at, a.slot_id,
           s.start_at, s.end_at, s.visit_type,
           s.doctor_id, d.name as doctor_name, d.specialty
    from public.appointments a
    join public.slots s on s.id = a.slot_id
    join public.doctors d on d.id = s.doctor_id
"""

DOCUMENT_COLUMNS = "id, kind, original_filename, content_type, size_bytes, created_at"


def my_appointments(
    conn: psycopg.Connection, patient_id: UUID, when: Literal["upcoming", "past"]
) -> list[Appointment]:
    """Booked appointments. Upcoming: soonest first. Past: most recent first."""
    if when == "upcoming":
        where, order = "s.start_at > now()", "s.start_at asc"
    else:
        where, order = "s.start_at <= now()", "s.start_at desc"
    rows = conn.execute(
        APPOINTMENT_SELECT
        + f" where a.patient_id = %s and a.status = 'booked' and {where} order by {order}",
        (patient_id,),
    ).fetchall()
    return [Appointment(**r) for r in rows]


def my_documents(conn: psycopg.Connection, patient_id: UUID) -> list[Document]:
    """Newest first."""
    rows = conn.execute(
        f"select {DOCUMENT_COLUMNS} from public.documents"
        " where patient_id = %s order by created_at desc",
        (patient_id,),
    ).fetchall()
    return [Document(**r) for r in rows]
