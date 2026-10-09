# /// script
# requires-python = ">=3.12"
# dependencies = ["psycopg[binary]>=3.2"]
# ///
"""Seed patients, doctors, slots and appointments into the local database.

Run from anywhere:  uv run scripts/seed.py

Clears the tables and re-inserts everything in one transaction, so running it twice
gives the same counts. Then creates the demo logins (see seed_auth.py). Ids are derived from the source data, so they are stable
across runs. Appointments are inserted directly (book_slot rejects past slots).
"""

import json
import os
import random
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from seed_auth import DemoLogin, email_for, seed_logins

ROOT = Path(__file__).resolve().parents[1]
SYNTHEA_DIR = ROOT / "data" / "synthea"
DOCTORS_FILE = ROOT / "data" / "doctors.json"
ENV_FILE = ROOT / ".env"

CLINIC_TZ = ZoneInfo("America/New_York")
DAY_START, DAY_END = time(9, 0), time(17, 0)
SLOT_MINUTES = 30
DAYS_BACK = DAYS_AHEAD = 30
RANDOM_SEED = 42
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "concierge-ai")

# (first_name, last_name) after stripping Synthea's digits. Each gets a patient login.
DEMO_PATIENTS = [("Aja", "Casper"), ("Bart", "Brekke")]
DEMO_STAFF = [("Nurse", "Kim")]


@dataclass
class Patient:
    id: uuid.UUID
    synthea_id: str
    first_name: str
    last_name: str
    birth_date: date
    gender: str  # used only to pick doctors; not stored


@dataclass
class Doctor:
    id: uuid.UUID
    name: str
    specialty: str
    visit_types: list[str]


@dataclass
class Slot:
    id: uuid.UUID
    doctor: Doctor
    start_at: datetime
    end_at: datetime
    visit_type: str


def stable_id(kind: str, key: str) -> uuid.UUID:
    return uuid.uuid5(ID_NAMESPACE, f"{kind}:{key}")


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def strip_digits(name: str) -> str:
    return re.sub(r"\d+", "", name)


def load_patients() -> list[Patient]:
    patients = []
    for path in sorted(SYNTHEA_DIR.glob("*.json")):
        bundle = json.loads(path.read_text())
        res = next(
            e["resource"] for e in bundle["entry"]
            if e["resource"]["resourceType"] == "Patient"
        )
        name = res["name"][0]
        patients.append(Patient(
            id=stable_id("patient", res["id"]),
            synthea_id=res["id"],
            first_name=strip_digits(name["given"][0]),
            last_name=strip_digits(name["family"]),
            birth_date=date.fromisoformat(res["birthDate"]),
            gender=res["gender"],
        ))
    return patients


def load_doctors() -> list[Doctor]:
    rows = json.loads(DOCTORS_FILE.read_text())
    return [
        Doctor(stable_id("doctor", r["name"]), r["name"], r["specialty"], r["visit_types"])
        for r in rows
    ]


def build_slots(doctors: list[Doctor], today: date) -> list[Slot]:
    """Weekday 30-min slots, 9am-5pm clinic time, today-30 .. today+30, in UTC.

    Doctors with two visit types use the first in the morning, the second after noon.
    """
    slots = []
    for offset in range(-DAYS_BACK, DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        local = datetime.combine(day, DAY_START, tzinfo=CLINIC_TZ)
        day_end = datetime.combine(day, DAY_END, tzinfo=CLINIC_TZ)
        while local < day_end:
            for doc in doctors:
                afternoon = local.hour >= 12 and len(doc.visit_types) > 1
                start = local.astimezone(timezone.utc)
                slots.append(Slot(
                    id=stable_id("slot", f"{doc.name}|{start.isoformat()}"),
                    doctor=doc,
                    start_at=start,
                    end_at=start + timedelta(minutes=SLOT_MINUTES),
                    visit_type=doc.visit_types[1 if afternoon else 0],
                ))
            local += timedelta(minutes=SLOT_MINUTES)
    return slots


def age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def can_see(patient: Patient, doctor: Doctor, today: date) -> bool:
    """Children see Pediatrics only. Adults never see Pediatrics. OB/GYN is female only."""
    is_child = age_on(patient.birth_date, today) < 18
    if is_child:
        return doctor.specialty == "Pediatrics"
    if doctor.specialty == "Pediatrics":
        return False
    if doctor.specialty == "OB/GYN":
        return patient.gender == "female"
    return True


def assign_appointments(
    patients: list[Patient], slots: list[Slot], now: datetime, today: date
) -> list[tuple[uuid.UUID, Patient, Slot, datetime]]:
    rng = random.Random(RANDOM_SEED)
    taken: set[uuid.UUID] = set()
    busy: set[tuple[uuid.UUID, datetime]] = set()
    rows = []

    def pick(patient: Patient, future: bool) -> None:
        pool = [
            s for s in slots
            if (s.start_at > now) == future
            and s.id not in taken
            and (patient.id, s.start_at) not in busy
            and can_see(patient, s.doctor, today)
        ]
        slot = rng.choice(pool)
        taken.add(slot.id)
        busy.add((patient.id, slot.start_at))
        created_at = min(slot.start_at - timedelta(days=rng.randint(3, 20)), now)
        appt_id = stable_id("appointment", f"{patient.synthea_id}|{slot.id}")
        rows.append((appt_id, patient, slot, created_at))

    demo_names = set(DEMO_PATIENTS)
    for p in patients:
        if (p.first_name, p.last_name) in demo_names:
            past, upcoming = 2, 1
        else:
            past, upcoming = rng.randint(1, 2), rng.randint(0, 1)
        for _ in range(past):
            pick(p, future=False)
        for _ in range(upcoming):
            pick(p, future=True)
    return rows


def main() -> None:
    load_env()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit(f"DATABASE_URL is not set (looked in {ENV_FILE})")

    now = datetime.now(timezone.utc)
    today = now.astimezone(CLINIC_TZ).date()

    patients = load_patients()
    doctors = load_doctors()
    slots = build_slots(doctors, today)
    appointments = assign_appointments(patients, slots, now, today)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        # One transaction: either everything is replaced or nothing changes.
        cur.execute(
            "truncate public.profiles, public.appointments, public.slots,"
            " public.doctors, public.patients"
        )
        cur.executemany(
            "insert into public.patients (id, synthea_id, first_name, last_name, birth_date)"
            " values (%s, %s, %s, %s, %s)",
            [(p.id, p.synthea_id, p.first_name, p.last_name, p.birth_date) for p in patients],
        )
        cur.executemany(
            "insert into public.doctors (id, name, specialty) values (%s, %s, %s)",
            [(d.id, d.name, d.specialty) for d in doctors],
        )
        with cur.copy(
            "copy public.slots (id, doctor_id, start_at, end_at, visit_type) from stdin"
        ) as copy:
            for s in slots:
                copy.write_row((s.id, s.doctor.id, s.start_at, s.end_at, s.visit_type))
        cur.executemany(
            "insert into public.appointments (id, patient_id, slot_id, status, created_at)"
            " values (%s, %s, %s, 'booked', %s)",
            [(a_id, p.id, s.id, created) for a_id, p, s, created in appointments],
        )
        conn.commit()

        logins = demo_logins(patients)
        seed_logins(conn, logins)

        print_summary(cur, patients, appointments, now)
        print_logins(logins)


def demo_logins(patients: list[Patient]) -> list[DemoLogin]:
    by_name = {(p.first_name, p.last_name): p for p in patients}
    logins = [
        DemoLogin(email_for(f, l), "patient", f"{f} {l}", by_name[(f, l)].id)
        for f, l in DEMO_PATIENTS
    ]
    logins += [DemoLogin(email_for(f, l), "staff", f"{f} {l}") for f, l in DEMO_STAFF]
    return logins


def print_logins(logins: list[DemoLogin]) -> None:
    print("\nDemo logins (password: DEMO_PASSWORD in .env):")
    for login in logins:
        link = f"  patient_id={login.patient_id}" if login.patient_id else ""
        print(f"  {login.role:<8} {login.email:<34} user_id={login.user_id}{link}")


def print_summary(cur: psycopg.Cursor, patients, appointments, now: datetime) -> None:
    print("Seeded:")
    for table in ("patients", "doctors", "slots", "appointments", "profiles"):
        cur.execute(f"select count(*) from public.{table}")
        print(f"  {table:<18}{cur.fetchone()[0]:>6}")
    cur.execute("select count(*) from public.open_slots")
    print(f"  {'open future slots':<18}{cur.fetchone()[0]:>6}")

    print("\nDemo patients:")
    for first, last in DEMO_PATIENTS:
        p = next(p for p in patients if (p.first_name, p.last_name) == (first, last))
        age = age_on(p.birth_date, now.date())
        print(f"  {p.first_name} {p.last_name} ({p.gender}, {age})  id={p.id}")
        for _, ap, s, _ in sorted(
            (a for a in appointments if a[1].id == p.id), key=lambda a: a[2].start_at
        ):
            when = s.start_at.astimezone(CLINIC_TZ).strftime("%a %b %d %I:%M %p %Z")
            tag = "upcoming" if s.start_at > now else "past    "
            print(f"    {tag}  {when}  {s.doctor.name} ({s.doctor.specialty}), {s.visit_type}")


if __name__ == "__main__":
    main()
