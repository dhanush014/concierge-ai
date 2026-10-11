"""Insurance cards: read one (vision model), confirm the fields, show the saved insurance.

The network status is a database lookup in plain code (app/insurance/match.py), never
the LLM. A document or insurance row that isn't yours gets the same 404 as one that
doesn't exist.
"""

import logging
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app import storage
from app.db import Conn
from app.deps import get_current_patient
from app.insurance.extract import read_card
from app.insurance.match import match_network, name_warning
from app.models import CardConfirm, CardFields, Insurance

router = APIRouter(prefix="/me", tags=["insurance"])
log = logging.getLogger(__name__)

PatientId = Annotated[UUID, Depends(get_current_patient)]

CARD_IMAGE_TYPES = ("image/jpeg", "image/png")
FIELDS = tuple(CardFields.model_fields)
COLUMNS = "id, status, created_at, card_path, " + ", ".join(FIELDS)


def to_insurance(conn: psycopg.Connection, row: dict, patient_id: UUID) -> Insurance:
    patient = conn.execute("select first_name, last_name from public.patients where id = %s", (patient_id,)).fetchone()
    match = match_network(conn, row["payer"], row["plan_name"])
    doc = conn.execute(
        "select id from public.documents where storage_path = %s and patient_id = %s", (row["card_path"], patient_id)
    ).fetchone()
    return Insurance(
        **{f: row[f] for f in FIELDS}, id=row["id"], status=row["status"], created_at=row["created_at"],
        document_id=doc["id"] if doc else None, network=match.status, matched_payer=match.payer,
        name_warning=name_warning(row["member_name"], patient["first_name"], patient["last_name"]),
    )


@router.post("/documents/{document_id}/extract")
def extract(conn: Conn, patient_id: PatientId, document_id: UUID) -> Insurance:
    """Read the card with the vision model and save the fields as 'extracted'. Reading the
    same card again replaces its earlier unconfirmed read."""
    doc = conn.execute(
        "select kind, content_type, storage_path from public.documents where id = %s and patient_id = %s",
        (document_id, patient_id),
    ).fetchone()
    if doc is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    if doc["kind"] != "insurance_card" or doc["content_type"] not in CARD_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="not_a_card_image")
    try:
        fields = read_card(storage.download(doc["storage_path"]), doc["content_type"])
    except Exception:  # model down, timeout, or output we couldn't parse
        log.exception("Reading card %s failed", document_id)
        raise HTTPException(status_code=502, detail="extraction_failed") from None

    conn.execute(
        "delete from public.patient_insurance where patient_id = %s and card_path = %s and status = 'extracted'",
        (patient_id, doc["storage_path"]),
    )
    row = conn.execute(
        f"insert into public.patient_insurance (patient_id, card_path, {', '.join(FIELDS)})"
        f" values (%s, %s, {', '.join(['%s'] * len(FIELDS))}) returning {COLUMNS}",
        (patient_id, doc["storage_path"], *(getattr(fields, f) for f in FIELDS)),
    ).fetchone()
    return to_insurance(conn, row, patient_id)


@router.post("/insurance/{insurance_id}/confirm")
def confirm(conn: Conn, patient_id: PatientId, insurance_id: UUID, body: CardConfirm) -> Insurance:
    """Save the fields as the patient confirmed them. A name warning is shown, not enforced."""
    row = conn.execute(
        f"update public.patient_insurance set status = 'confirmed', {', '.join(f'{f} = %s' for f in FIELDS)}"
        f" where id = %s and patient_id = %s returning {COLUMNS}",
        (*(getattr(body, f) or None for f in FIELDS), insurance_id, patient_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="insurance_not_found")
    return to_insurance(conn, row, patient_id)


@router.get("/insurance")
def my_insurance(conn: Conn, patient_id: PatientId) -> Insurance | None:
    """Your most recently confirmed insurance, or null."""
    row = conn.execute(
        f"select {COLUMNS} from public.patient_insurance where patient_id = %s and status = 'confirmed'"
        " order by created_at desc, id desc limit 1",
        (patient_id,),
    ).fetchone()
    return None if row is None else to_insurance(conn, row, patient_id)
