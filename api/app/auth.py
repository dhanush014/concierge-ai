"""Verify Supabase access tokens.

This Supabase version signs user tokens with ES256 (asymmetric). We verify with the
public keys published at {SUPABASE_URL}/auth/v1/.well-known/jwks.json. PyJWKClient
caches them and refetches once when a token has a key id it hasn't seen (key rotation).
"""

import os
from functools import lru_cache
from typing import Any

import jwt

from app.db import load_env

ALGORITHMS = ["ES256"]
AUDIENCE = "authenticated"
LEEWAY_SECONDS = 30  # tolerate small clock differences on exp/iat


class InvalidToken(Exception):
    pass


@lru_cache
def issuer() -> str:
    load_env()
    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL is not set")
    return f"{url.rstrip('/')}/auth/v1"


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer()}/.well-known/jwks.json", cache_keys=True)


def signing_key(token: str) -> Any:
    """Public key matching the token's key id. Tests swap this out."""
    return jwks_client().get_signing_key_from_jwt(token).key


def verify_token(token: str) -> dict[str, Any]:
    """Return the token's claims, or raise InvalidToken."""
    try:
        return jwt.decode(
            token,
            signing_key(token),
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            issuer=issuer(),
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
