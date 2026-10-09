"""Test helper: create Supabase Auth users and get real access tokens."""

import os
import secrets

import httpx

from app.db import load_env


class SupabaseAuth:
    def __init__(self) -> None:
        load_env()
        self.url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1"
        self.service_key = os.environ["SUPABASE_SERVICE_KEY"]
        self.anon_key = os.environ["SUPABASE_ANON_KEY"]
        self.http = httpx.Client(timeout=10)

    def _admin_headers(self) -> dict[str, str]:
        return {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}

    def create_user_and_sign_in(self, email: str) -> tuple[str, str]:
        """Returns (user_id, access_token)."""
        password = secrets.token_urlsafe(16)
        resp = self.http.post(
            f"{self.url}/admin/users",
            headers=self._admin_headers(),
            json={"email": email, "password": password, "email_confirm": True},
        )
        resp.raise_for_status()
        user_id = resp.json()["id"]

        resp = self.http.post(
            f"{self.url}/token?grant_type=password",
            headers={"apikey": self.anon_key},
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        return user_id, resp.json()["access_token"]

    def delete_user(self, user_id: str) -> None:
        self.http.delete(f"{self.url}/admin/users/{user_id}", headers=self._admin_headers())
