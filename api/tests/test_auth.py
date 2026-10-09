"""Login tokens, roles, and the browser being locked out of the database."""

import time
from datetime import timedelta

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import auth
from tests.conftest import TOKENS, Factory, as_patient, bearer
from tests.supabase_auth import SupabaseAuth


def user_id_for(db: psycopg.Connection, patient_id) -> str:
    row = db.execute("select id from public.profiles where patient_id = %s", (patient_id,)).fetchone()
    return str(row["id"])


def forged_token(private_key, *, sub: str, kid: str, expires_in: int) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": auth.AUDIENCE,
        "iss": auth.issuer(),
        "role": "authenticated",
        "iat": now - 120,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})


# --- 401s -----------------------------------------------------------------------


def test_no_token_is_401(client: TestClient) -> None:
    resp = client.get("/me/appointments")
    assert (resp.status_code, resp.json()["detail"]) == (401, "missing_token")
    assert resp.headers["www-authenticate"] == "Bearer"


def test_garbage_token_is_401(client: TestClient) -> None:
    resp = client.get("/me/appointments", headers=bearer("not.a.jwt"))
    assert (resp.status_code, resp.json()["detail"]) == (401, "invalid_token")


def test_token_signed_with_another_key_is_401(
    client: TestClient, make: Factory, db: psycopg.Connection
) -> None:
    pat = make.patient()
    real_kid = jwt.get_unverified_header(TOKENS[pat])["kid"]
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    token = forged_token(attacker_key, sub=user_id_for(db, pat), kid=real_kid, expires_in=3600)

    resp = client.get("/me/appointments", headers=bearer(token))

    assert (resp.status_code, resp.json()["detail"]) == (401, "invalid_token")


def test_valid_token_without_profile_is_401(client: TestClient, make: Factory) -> None:
    resp = client.get("/me/appointments", headers=bearer(make.token_without_profile()))
    assert (resp.status_code, resp.json()["detail"]) == (401, "no_profile")


@pytest.mark.parametrize(("expired_seconds_ago", "status"), [(10, 200), (60, 401)])
def test_expiry_has_30_second_leeway(
    client: TestClient,
    make: Factory,
    db: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
    expired_seconds_ago: int,
    status: int,
) -> None:
    # Sign with our own key and make the API trust it, so we control exp precisely.
    test_key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "signing_key", lambda token: test_key.public_key())
    pat = make.patient()
    token = forged_token(
        test_key, sub=user_id_for(db, pat), kid="test", expires_in=-expired_seconds_ago
    )

    resp = client.get("/me/appointments", headers=bearer(token))

    assert resp.status_code == status


# --- roles ----------------------------------------------------------------------


def test_staff_token_is_403_on_patient_routes(client: TestClient, make: Factory) -> None:
    staff = bearer(make.staff_token())
    slot = make.slot(make.doctor(), timedelta(days=1))

    mine = client.get("/me/appointments", headers=staff)
    booked = client.post("/appointments", json={"slot_id": str(slot)}, headers=staff)

    assert (mine.status_code, mine.json()["detail"]) == (403, "patients_only")
    assert (booked.status_code, booked.json()["detail"]) == (403, "patients_only")


def test_patient_token_reaches_own_appointments(client: TestClient, make: Factory) -> None:
    resp = client.get("/me/appointments", headers=as_patient(make.patient()))
    assert (resp.status_code, resp.json()) == (200, [])


# --- browser keys cannot touch the database directly ----------------------------


def test_browser_keys_cannot_read_tables_or_book(
    make: Factory, db: psycopg.Connection, supabase_auth: SupabaseAuth
) -> None:
    pat = make.patient()
    slot = make.slot(make.doctor(), timedelta(days=1))
    rest = supabase_auth.url.removesuffix("/auth/v1") + "/rest/v1"
    anon = {"apikey": supabase_auth.anon_key}
    logged_in = {**anon, **as_patient(pat)}

    for headers in (anon, logged_in):
        for table in ("patients", "doctors", "slots", "open_slots", "appointments", "profiles"):
            resp = supabase_auth.http.get(f"{rest}/{table}?select=*", headers=headers)
            assert (resp.status_code, resp.json()) == (200, []), table

        resp = supabase_auth.http.post(
            f"{rest}/rpc/book_slot",
            headers=headers,
            json={"p_patient_id": str(pat), "p_slot_id": str(slot)},
        )
        assert resp.status_code in (401, 403)

    booked = db.execute(
        "select count(*) as n from public.appointments where slot_id = %s", (slot,)
    ).fetchone()
    assert booked["n"] == 0
