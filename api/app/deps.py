"""Request dependencies shared by routes."""

from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException

from app.db import Conn


def get_current_patient(
    conn: Conn,
    x_patient_id: Annotated[str | None, Header()] = None,
) -> UUID:
    """Who is calling. Until Phase 2 this trusts the X-Patient-Id header.

    Phase 2 replaces only this function (read the Supabase Auth token, look up the
    profile's patient_id). Endpoints keep depending on it unchanged.
    """
    if not x_patient_id:
        raise HTTPException(status_code=401, detail="missing_patient")
    try:
        patient_id = UUID(x_patient_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="unknown_patient") from None

    row = conn.execute("select 1 from public.patients where id = %s", (patient_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown_patient")
    return patient_id
