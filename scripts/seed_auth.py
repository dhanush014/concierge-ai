"""Demo logins for seed.py: Supabase Auth users and their profiles.

Uses the Supabase Auth admin API (service key) through urllib, so no extra library.
Re-running keeps each user's id and just resets the password, so ids stay stable.
"""

import json
import os
import urllib.request
import uuid
from dataclasses import dataclass

import psycopg

EMAIL_DOMAIN = "demo.concierge.test"


@dataclass
class DemoLogin:
    email: str
    role: str  # 'patient' | 'staff'
    display_name: str
    patient_id: uuid.UUID | None = None
    user_id: str = ""


class AdminApi:
    def __init__(self, url: str, service_key: str) -> None:
        self.url = url.rstrip("/")
        self.key = service_key

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"{self.url}/auth/v1{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read() or b"{}")

    def find_user_id(self, email: str) -> str | None:
        users = self._call("GET", "/admin/users?page=1&per_page=1000").get("users", [])
        return next((u["id"] for u in users if u.get("email") == email), None)

    def upsert_user(self, email: str, password: str, display_name: str) -> str:
        body = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"display_name": display_name},
        }
        existing = self.find_user_id(email)
        if existing:
            return self._call("PUT", f"/admin/users/{existing}", body)["id"]
        return self._call("POST", "/admin/users", body)["id"]


def email_for(first: str, last: str) -> str:
    return f"{first}.{last}@{EMAIL_DOMAIN}".lower()


def seed_logins(conn: psycopg.Connection, logins: list[DemoLogin]) -> None:
    """Create or update each auth user, then upsert its profile. Fills login.user_id."""
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        raise SystemExit("DEMO_PASSWORD is not set in .env")
    api = AdminApi(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    for login in logins:
        login.user_id = api.upsert_user(login.email, password, login.display_name)
        conn.execute(
            "insert into public.profiles (id, role, patient_id, display_name)"
            " values (%s, %s, %s, %s)"
            " on conflict (id) do update set role = excluded.role,"
            " patient_id = excluded.patient_id, display_name = excluded.display_name",
            (login.user_id, login.role, login.patient_id, login.display_name),
        )
    conn.commit()
