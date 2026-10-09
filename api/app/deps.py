"""Request dependencies shared by routes: who is calling."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth import InvalidToken, verify_token
from app.db import Conn

# auto_error=False so we return our own 401s. Also adds the Authorize button to /docs.
bearer = HTTPBearer(auto_error=False, description="Supabase access token")


class CurrentUser(BaseModel):
    id: UUID
    role: Literal["patient", "staff"]
    patient_id: UUID | None
    display_name: str


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def current_user(
    conn: Conn,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser:
    """The logged-in user: a valid Supabase token whose user has a profile."""
    if credentials is None:
        raise unauthorized("missing_token")
    try:
        claims = verify_token(credentials.credentials)
    except InvalidToken:
        raise unauthorized("invalid_token") from None

    row = conn.execute(
        "select id, role, patient_id, display_name from public.profiles where id = %s",
        (claims["sub"],),
    ).fetchone()
    if row is None:
        raise unauthorized("no_profile")
    return CurrentUser(**row)


def get_current_patient(user: Annotated[CurrentUser, Depends(current_user)]) -> UUID:
    """The patient id of the logged-in patient. Staff get 403 on patient routes."""
    if user.role != "patient" or user.patient_id is None:
        raise HTTPException(status_code=403, detail="patients_only")
    return user.patient_id
