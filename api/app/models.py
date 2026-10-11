"""Request and response bodies. All datetimes are UTC."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints


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


ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ChatRequest(BaseModel):
    conversation_id: UUID | None = None
    message: ChatText


class SourceRef(BaseModel):
    """A source an answer cites: shown under the reply."""

    tag: str  # "S-3f2a", as cited in the text
    kind: Literal["record", "policy", "appointment", "document"]
    title: str  # "Lab result", "Parking"
    section: str | None  # "Hemoglobin A1c", "Validation"
    date: str | None  # ISO date


class Message(BaseModel):
    id: UUID
    sender: Literal["patient", "assistant", "staff"]
    kind: Literal["text", "emergency", "handoff", "notice"]
    content: str
    created_at: datetime
    staff_name: str | None = None
    sources: list[SourceRef] | None = None


class Conversation(BaseModel):
    id: UUID
    status: Literal["bot", "handoff", "closed"]
    created_at: datetime
    messages: list[Message]


class Handoff(BaseModel):
    id: UUID
    conversation_id: UUID
    patient_name: str
    reason: Literal["emergency", "clinical", "wants_human"]
    summary: str
    status: Literal["open", "active", "closed"]
    staff_id: UUID | None
    staff_name: str | None
    created_at: datetime
    closed_at: datetime | None


class HandoffDetail(Handoff):
    messages: list[Message]
    trace_url: str | None


StaffText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class StaffMessageRequest(BaseModel):
    content: StaffText
