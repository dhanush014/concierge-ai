"""Every model name, timeout and fixed reply the agent uses. Change them here only."""

from zoneinfo import ZoneInfo

# Groq models, by job.
SAFETY_MODEL = "openai/gpt-oss-20b"
AGENT_MODEL = "openai/gpt-oss-120b"  # picks tools and writes the answer
SUMMARY_MODEL = "openai/gpt-oss-20b"  # one-line handoff summary for staff
# Reads insurance cards. The only vision-capable model Groq lists (checked 2026-10-11);
# gpt-oss rejects image input.
VISION_MODEL = "qwen/qwen3.8-27b"

# Local embeddings for RAG (sentence-transformers, runs on this machine).
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIMS = 384
# bge's instruction for queries (documents are embedded without it).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RERANK_MODEL = "BAAI/bge-reranker-base"  # cross-encoder, local
RETRIEVE_CANDIDATES = 25  # nearest chunks pulled by vector search, then reranked
RETRIEVE_TOP_N = 5  # kept after reranking

# The safety LLM gets this long before the cascade falls back to its regex flag.
SAFETY_TIMEOUT_SECONDS = 3.0
AGENT_TIMEOUT_SECONDS = 30.0
SUMMARY_TIMEOUT_SECONDS = 5.0
VISION_TIMEOUT_SECONDS = 30.0

# Same clinic time zone as the web app (web/lib/time.ts). Tool results are turned
# into clinic time in code so the LLM never does time-zone math.
CLINIC_TZ = ZoneInfo("America/New_York")

HISTORY_TURNS = 6  # earlier messages (questions and answers) the agent sees
MAX_TOOL_CALLS = 4  # per turn; after that the agent must answer with what it has

EMERGENCY_REPLY = (
    "If this is an emergency, call 911 now or go to the nearest emergency room. "
    "If you are thinking about harming yourself, call or text 988."
)
NURSE_REPLY = (
    "Connecting you to a nurse. They'll reply here as soon as they can. "
    "If it gets worse or feels urgent, call 911."
)
# Every answer that used the coverage tool ends with this (added in code if missing).
COVERAGE_DISCLAIMER = "This is an estimate. Confirm with your insurer."
BILLING_PHONE = "555-0142"

# Notices: short system lines in the chat (messages.kind = 'notice').
NURSE_NOTIFIED_NOTICE = "A nurse has been notified and will join this chat."
ASSISTANT_BACK_NOTICE = "The assistant is back. Ask me about your records, appointments or hospital policies."
STAFF_JOINED_NOTICE = "{name} joined the chat."
