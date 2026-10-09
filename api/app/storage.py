"""Supabase Storage for patient documents, through its REST API with the service key.

Only the backend talks to Storage. The bucket is private and has no browser policies.
"""

import os
from functools import lru_cache

import httpx

from app.db import load_env

BUCKET = "patient-docs"
SIGNED_URL_SECONDS = 60


class StorageError(Exception):
    pass


@lru_cache
def storage_base_url() -> str:
    load_env()
    return os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1"


@lru_cache
def client() -> httpx.Client:
    load_env()
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return httpx.Client(
        base_url=storage_base_url(),
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )


def _check(resp: httpx.Response, action: str) -> httpx.Response:
    if resp.status_code >= 300:
        raise StorageError(f"{action} failed: {resp.status_code} {resp.text[:200]}")
    return resp


def upload(path: str, data: bytes, content_type: str) -> None:
    resp = client().post(
        f"/object/{BUCKET}/{path}",
        content=data,
        headers={"Content-Type": content_type, "x-upsert": "false"},
    )
    _check(resp, "upload")


def remove(path: str) -> None:
    resp = client().request("DELETE", f"/object/{BUCKET}", json={"prefixes": [path]})
    _check(resp, "delete")


def signed_url(path: str) -> str:
    """A link anyone can open until it expires (SIGNED_URL_SECONDS)."""
    resp = client().post(f"/object/sign/{BUCKET}/{path}", json={"expiresIn": SIGNED_URL_SECONDS})
    signed = _check(resp, "sign").json()["signedURL"]  # "/object/sign/<bucket>/<path>?token=..."
    return storage_base_url() + signed
