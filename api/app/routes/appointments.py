"""Doctors, open slots and appointments.

Plain SQL only. Booking rules live in the database functions book_slot,
cancel_appointment and reschedule_appointment; errors they raise are turned
into HTTP responses by app.db.db_error_handler.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends

from app.db import Conn
from app.deps import get_current_patient
from app.models import Appointment, BookRequest, Doctor, RescheduleRequest, Slot

router = APIRouter(tags=["appointments"])

PatientId = Annotated[UUID, Depends(get_current_patient)]

SLOT_WINDOW = timedelta(days=14)
SLOT_LIMIT = 200

APPOINTMENT_SELECT = """
    select a.id, a.status, a.created_at, a.slot_id,
           s.start_at, s.end_at, s.visit_type,
           s.doctor_id, d.name as doctor_name, d.specialty
    from public.appointments a
    join public.slots s on s.id = a.slot_id
    join public.doctors d on d.id = s.doctor_id
"""


def as_utc(value: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def fetch_appointment(conn: psycopg.Connection, appointment_id: UUID) -> Appointment:
    row = conn.execute(APPOINTMENT_SELECT + " where a.id = %s", (appointment_id,)).fetchone()
    return Appointment(**row)


@router.get("/doctors")
def list_doctors(conn: Conn) -> list[Doctor]:
    rows = conn.execute(
        """
        select d.id, d.name, d.specialty,
               coalesce(
                 array_agg(distinct s.visit_type order by s.visit_type)
                   filter (where s.visit_type is not null),
                 '{}'
               ) as visit_types
        from public.doctors d
        left join public.slots s on s.doctor_id = d.id
        group by d.id
        order by d.name
        """
    ).fetchall()
    return [Doctor(**r) for r in rows]


@router.get("/slots")
def list_slots(
    conn: Conn,
    doctor_id: UUID | None = None,
    visit_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Slot]:
    """Open future slots, earliest first, at most 200.

    Defaults: date_from = now, date_to = date_from + 14 days. Past slots are never
    returned because open_slots only contains future slots.
    """
    start = as_utc(date_from) or datetime.now(timezone.utc)
    end = as_utc(date_to) or start + SLOT_WINDOW
    rows = conn.execute(
        """
        select id, doctor_id, start_at, end_at, visit_type
        from public.open_slots
        where start_at >= %(start)s
          and start_at < %(end)s
          and (%(doctor_id)s::uuid is null or doctor_id = %(doctor_id)s)
          and (%(visit_type)s::text is null or visit_type = %(visit_type)s)
        order by start_at, doctor_id
        limit %(limit)s
        """,
        {
            "start": start,
            "end": end,
            "doctor_id": doctor_id,
            "visit_type": visit_type,
            "limit": SLOT_LIMIT,
        },
    ).fetchall()
    return [Slot(**r) for r in rows]


@router.get("/me/appointments")
def my_appointments(
    conn: Conn,
    patient_id: PatientId,
    when: Literal["upcoming", "past"] = "upcoming",
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


@router.post("/appointments", status_code=201)
def book(conn: Conn, patient_id: PatientId, body: BookRequest) -> Appointment:
    row = conn.execute(
        "select (public.book_slot(%s, %s)).id", (patient_id, body.slot_id)
    ).fetchone()
    return fetch_appointment(conn, row["id"])


@router.post("/appointments/{appointment_id}/cancel")
def cancel(conn: Conn, patient_id: PatientId, appointment_id: UUID) -> Appointment:
    row = conn.execute(
        "select (public.cancel_appointment(%s, %s)).id", (appointment_id, patient_id)
    ).fetchone()
    return fetch_appointment(conn, row["id"])


@router.post("/appointments/{appointment_id}/reschedule", status_code=201)
def reschedule(
    conn: Conn, patient_id: PatientId, appointment_id: UUID, body: RescheduleRequest
) -> Appointment:
    row = conn.execute(
        "select (public.reschedule_appointment(%s, %s, %s)).id",
        (appointment_id, patient_id, body.new_slot_id),
    ).fetchone()
    return fetch_appointment(conn, row["id"])
