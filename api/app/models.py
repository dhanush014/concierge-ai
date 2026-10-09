"""Request and response bodies. All datetimes are UTC."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class Doctor(BaseModel):
    id: UUID
    name: str
    specialty: str
    visit_types: list[str]


class Slot(BaseModel):
    id: UUID
    doctor_id: UUID
    start_at: datetime
    end_at: datetime
    visit_type: str


class Appointment(BaseModel):
    id: UUID
    status: Literal["booked", "cancelled"]
    created_at: datetime
    slot_id: UUID
    start_at: datetime
    end_at: datetime
    visit_type: str
    doctor_id: UUID
    doctor_name: str
    specialty: str


class BookRequest(BaseModel):
    slot_id: UUID


class RescheduleRequest(BaseModel):
    new_slot_id: UUID


class Document(BaseModel):
    id: UUID
    kind: Literal["insurance_card", "referral"]
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class SignedUrl(BaseModel):
    url: str
    expires_in: int
