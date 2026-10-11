"""Every model name, timeout and fixed reply the agent uses. Change them here only."""

from zoneinfo import ZoneInfo

# Groq models, by job.
SAFETY_MODEL = "openai/gpt-oss-20b"
ROUTER_MODEL = "openai/gpt-oss-20b"
ANSWER_MODEL = "openai/gpt-oss-120b"
SUMMARY_MODEL = "openai/gpt-oss-20b"  # one-line handoff summary for staff

# Local embeddings for RAG (sentence-transformers, runs on this machine).
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIMS = 384

# The safety LLM gets this long before the cascade falls back to its regex flag.
SAFETY_TIMEOUT_SECONDS = 3.0
ROUTER_TIMEOUT_SECONDS = 3.0
ANSWER_TIMEOUT_SECONDS = 30.0
SUMMARY_TIMEOUT_SECONDS = 5.0

# Same clinic time zone as the web app (web/lib/time.ts). Tool results are turned
# into clinic time in code so the LLM never does time-zone math.
CLINIC_TZ = ZoneInfo("America/New_York")

HISTORY_TURNS = 6  # recent messages the router and answer models see

EMERGENCY_REPLY = (
    "If this is an emergency, call 911 now or go to the nearest emergency room. "
    "If you are thinking about harming yourself, call or text 988."
)
NURSE_REPLY = (
    "Connecting you to a nurse. They'll reply here as soon as they can. "
    "If it gets worse or feels urgent, call 911."
)
# Notices: short system lines in the chat (messages.kind = 'notice').
NURSE_NOTIFIED_NOTICE = "A nurse has been notified and will join this chat."
ASSISTANT_BACK_NOTICE = "The assistant is back. Ask me about your appointments or documents."
STAFF_JOINED_NOTICE = "{name} joined the chat."
CHANGE_APPOINTMENT_REPLY = (
    "I can't book, reschedule or cancel visits in chat. "
    "Use the Appointments tab: it shows open times and makes the change right away."
)
OTHER_REPLY = (
    "I can tell you about your upcoming or past appointments and the documents "
    "you've uploaded. For anything else, please call the front desk."
)
