"""Find open appointment times for the agent. The agent never books.

When exactly one open slot matches the doctor, day and time the patient asked for,
the tool returns a proposal. The chat route turns it into an action on the reply: a
link to the booking review page with doctor, visit type and slot filled in, which the
chat opens. The patient books by pressing Confirm booking there (plain code, as always).
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

import psycopg
from langchain_core.messages import ToolMessage

from app.agent.config import CLINIC_TZ
from app.agent.tools import clinic_time

TOOL_NAME = "find_open_times"
MAX_LISTED = 10
NEXT_DAYS = 14  # nothing that day: look this far ahead
STOP_WORDS = {"dr", "dr.", "doctor", "the", "with", "a", "an", "and", "or", "my"}


@dataclass
class Proposal:
    slot_id: str
    doctor_id: str
    visit_type: str
    start_at: str  # ISO, UTC

    def action(self) -> dict:
        query = urlencode({"doctor": self.doctor_id, "type": self.visit_type, "slot": self.slot_id})
        return {"label": "Review and book", "href": f"/portal/appointments/book?{query}"}


def doctor_matches(wanted: str | None, name: str, specialty: str) -> bool:
    """Every word of the request (first 5 letters, so "cardiologist" finds Cardiology)
    appears in the doctor's name or specialty."""
    if not wanted:
        return True
    hay = f"{name} {specialty}".lower()
    words = [w.strip(".,") for w in wanted.lower().split() if w not in STOP_WORDS]
    return all(w[:5] in hay for w in words if w)


def _line(slot: dict) -> str:
    return f"{clinic_time(slot['start_at'])}: {slot['visit_type']} with {slot['name']} ({slot['specialty']})"


def find_open_times(
    conn: psycopg.Connection, day: date, at: time | None, doctor: str | None
) -> tuple[str, list[dict]]:
    """(text for the LLM, [proposal] or [])."""
    doctors = conn.execute("select id, name, specialty from public.doctors order by name").fetchall()
    chosen = [d["id"] for d in doctors if doctor_matches(doctor, d["name"], d["specialty"])]
    if not chosen:
        listing = "; ".join(f"{d['name']} ({d['specialty']})" for d in doctors)
        return f"No doctor matches {doctor!r}. Our doctors: {listing}.", []

    today = datetime.now(CLINIC_TZ).date()
    if day < today:
        return f"{day:%a, %b %-d, %Y} has passed. Today is {today:%a, %b %-d, %Y}.", []

    start = datetime.combine(day, time(0), CLINIC_TZ)
    rows = conn.execute(
        "select s.id, s.doctor_id, s.start_at, s.visit_type, d.name, d.specialty"
        " from public.open_slots s join public.doctors d on d.id = s.doctor_id"
        " where s.doctor_id = any(%s) and s.start_at > now() and s.start_at >= %s and s.start_at < %s"
        " order by s.start_at, d.name",
        (chosen, start, start + timedelta(days=NEXT_DAYS)),
    ).fetchall()
    that_day = [r for r in rows if r["start_at"].astimezone(CLINIC_TZ).date() == day]
    if not rows:
        return f"No open times from {day:%b %-d} for the next {NEXT_DAYS} days.", []

    if at is not None:
        exact = [r for r in that_day if r["start_at"].astimezone(CLINIC_TZ).time().replace(tzinfo=None) == at]
        if len(exact) == 1:
            slot = exact[0]
            proposal = Proposal(str(slot["id"]), str(slot["doctor_id"]), slot["visit_type"],
                                slot["start_at"].isoformat())
            return (f"Open, exactly as asked: {_line(slot)}. The booking page is opening for the patient to "
                    "review and press Confirm booking. Tell them that; don't say it is booked."), [asdict(proposal)]
        if len(exact) > 1:
            return ("Open at that time with more than one doctor; ask which one:\n"
                    + "\n".join(_line(r) for r in exact)), []

    if that_day:
        if at is not None:  # closest to the asked time first
            minutes = at.hour * 60 + at.minute
            that_day.sort(key=lambda r: abs(r["start_at"].astimezone(CLINIC_TZ).hour * 60
                                            + r["start_at"].astimezone(CLINIC_TZ).minute - minutes))
        header = (f"Not open at {at:%-I:%M %p}. " if at is not None else "") + f"Open times on {day:%a, %b %-d}:"
        return header + "\n" + "\n".join(_line(r) for r in that_day[:MAX_LISTED]), []
    return (f"No open times on {day:%a, %b %-d}. The next open times:\n"
            + "\n".join(_line(r) for r in rows[:MAX_LISTED])), []


def action_for(tool_messages: list[ToolMessage]) -> dict | None:
    """The reply's action: from the turn's last find_open_times call, if it matched."""
    calls = [m for m in tool_messages if m.name == TOOL_NAME]
    if not calls or not calls[-1].artifact:
        return None
    return Proposal(**calls[-1].artifact[0]).action()


def parse_day(value: str) -> date:
    return date.fromisoformat(value.strip())


def parse_time(value: str | None) -> time | None:
    if not value or not value.strip():
        return None
    return time.fromisoformat(value.strip()[:5])

