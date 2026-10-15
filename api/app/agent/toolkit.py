"""The agent's tools: read-only, one patient's data.

`patient_id` is injected from graph state (set from the login token by the chat route).
InjectedState keeps it out of the tool schema the LLM sees, so the LLM can neither
read nor choose it. Each tool returns (text for the LLM, sources) - the sources ride
along as the ToolMessage artifact and become the "Sources" under the answer.
"""

from typing import Annotated, Literal
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState
from psycopg_pool import ConnectionPool

from app.agent import booking
from app.agent import record_tools as rt
from app.agent.tools import appointment_lines, document_lines

PatientId = Annotated[str, InjectedState("patient_id")]
RecordKind = Literal["medications", "conditions", "allergies", "immunizations", "visits"]


def make_tools(pool: ConnectionPool) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def get_my_appointments(patient_id: PatientId) -> tuple[str, list[dict]]:
        """The patient's upcoming appointments (soonest first) and recent past ones at
        Riverside Health: date, time, visit type, doctor."""
        with pool.connection() as conn:
            return rt.render("Appointments:", appointment_lines(conn, UUID(patient_id)), "No appointments found.")

    @tool(response_format="content_and_artifact")
    def get_my_documents(patient_id: PatientId) -> tuple[str, list[dict]]:
        """Documents the patient uploaded (insurance cards, referrals), newest first."""
        with pool.connection() as conn:
            return rt.render("Uploaded documents:", document_lines(conn, UUID(patient_id)), "No documents uploaded.")

    @tool(response_format="content_and_artifact")
    def get_lab_results(test_name: str, patient_id: PatientId, limit: int = 3) -> tuple[str, list[dict]]:
        """Lab results and vital signs by test name, e.g. "A1c", "cholesterol", "LDL",
        "blood pressure", "weight", "creatinine". Returns the latest `limit` values of
        every matching test, newest first ("cholesterol" gives total, HDL and LDL)."""
        with pool.connection() as conn:
            lines = rt.lab_results(conn, UUID(patient_id), test_name, per_test=max(1, min(limit, 10)))
        return rt.render(f"Lab results and vitals matching {test_name!r}:", lines, "No matching results found.")

    @tool(response_format="content_and_artifact")
    def list_my_records(kind: RecordKind, patient_id: PatientId) -> tuple[str, list[dict]]:
        """Everything of one kind in the patient's medical record: medications,
        conditions, allergies, immunizations or visits (past clinical encounters).
        Repeats are collapsed; current (active) items first."""
        with pool.connection() as conn:
            lines, total = rt.list_records(conn, UUID(patient_id), kind)
        # A cut list must say so: "not in this list" must never read as "not in the record".
        more = f" (showing {len(lines)} of {total}; use search_my_records for others)" if total > len(lines) else ""
        return rt.render(f"Your {kind}{more}:", lines, f"No {kind} found in your record.")

    @tool(response_format="content_and_artifact")
    def search_my_records(query: str, patient_id: PatientId) -> tuple[str, list[dict]]:
        """Search the patient's medical record by meaning, for anything the other record
        tools don't cover (procedures, surveys, a specific past event)."""
        with pool.connection() as conn:
            lines = rt.search_records(conn, UUID(patient_id), query)
        return rt.render(f"Records matching {query!r}:", lines, "Nothing in your record matched.")

    @tool(response_format="content_and_artifact")
    def search_hospital_policies(query: str) -> tuple[str, list[dict]]:
        """Search Riverside Health's policies: lab and fasting prep, imaging prep, visiting
        hours, billing and payment plans, medical records requests, cancellations and
        no-shows, telehealth, parking."""
        with pool.connection() as conn:
            lines = rt.search_policies(conn, query)
        return rt.render(f"Hospital policies matching {query!r}:", lines, "No policy matched.")

    @tool(response_format="content_and_artifact")
    def find_open_times(date: str, time: str | None = None, doctor: str | None = None) -> tuple[str, list[dict]]:
        """Open appointment times on a day (date "YYYY-MM-DD"), optionally at a time
        ("HH:MM", 24-hour) and with a doctor (name or specialty, e.g. "Patel",
        "cardiology"). If exactly one open time matches, the booking page opens for the
        patient to confirm. Lists our doctors if none matches; lists nearby open times
        if the exact time isn't open. You cannot book: the patient confirms."""
        try:
            day, at = booking.parse_day(date), booking.parse_time(time)
        except ValueError:
            return 'Use date "YYYY-MM-DD" and time "HH:MM" (24-hour).', []
        with pool.connection() as conn:
            return booking.find_open_times(conn, day, at, doctor)

    @tool(response_format="content_and_artifact")
    def check_my_coverage(question: str, patient_id: PatientId) -> tuple[str, list[dict]]:
        """What the patient's own insurance plan covers: copays, deductible, out-of-pocket
        maximum, prior authorization, referrals, what's not covered, appeals. Uses their
        confirmed insurance card; tells you if there is none or the plan isn't in network."""
        with pool.connection() as conn:
            result = rt.coverage(conn, UUID(patient_id), question)
        return rt.render(result.header, result.lines, "No matching part of the plan document.") if result.lines \
            else (result.header, [])

    return [get_my_appointments, get_my_documents, get_lab_results, list_my_records,
            search_my_records, search_hospital_policies, check_my_coverage, find_open_times]
