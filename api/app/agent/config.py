"""Every model name, timeout and fixed reply the agent uses. Change them here only."""

from zoneinfo import ZoneInfo

# Groq models, by job.
SAFETY_MODEL = "openai/gpt-oss-20b"
ROUTER_MODEL = "openai/gpt-oss-20b"
ANSWER_MODEL = "openai/gpt-oss-120b"

# The safety LLM gets this long before the cascade falls back to its regex flag.
SAFETY_TIMEOUT_SECONDS = 3.0
ROUTER_TIMEOUT_SECONDS = 3.0
ANSWER_TIMEOUT_SECONDS = 30.0

# Same clinic time zone as the web app (web/lib/time.ts). Tool results are turned
# into clinic time in code so the LLM never does time-zone math.
CLINIC_TZ = ZoneInfo("America/New_York")

HISTORY_TURNS = 6  # recent messages the router and answer models see

EMERGENCY_REPLY = (
    "If this is an emergency, call 911 now or go to the nearest emergency room. "
    "If you are thinking about harming yourself, call or text 988."
)
NURSE_REPLY = (
    "I can't help with that here, but a nurse will follow up with you. "
    "If it gets worse or feels urgent, call 911."
)
CHANGE_APPOINTMENT_REPLY = (
    "I can't book, reschedule or cancel visits in chat. "
    "Use the Appointments tab: it shows open times and makes the change right away."
)
OTHER_REPLY = (
    "I can tell you about your upcoming or past appointments and the documents "
    "you've uploaded. For anything else, please call the front desk."
)
