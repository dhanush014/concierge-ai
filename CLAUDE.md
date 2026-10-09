# CLAUDE.md

Concierge AI: a hospital patient portal with appointments, an insurance card check, and an AI chat assistant with live human handoff. Full design is in `SPEC.md`. Read it before starting any task.

## Current phase

Phase 1. (Update this line at the start of each phase.)

## How to work

* Work ONLY on the phase named in my message. Do not start the next phase.
* Before writing code, show a short plan (files to create or change) and wait for my OK.
* When done, stop and tell me exactly how to verify it (commands to run, what I should see).
* Do not invent features, screens, or tables that are not in SPEC.md. If something seems missing, ask.
* No new libraries without asking first.
* Keep files small and focused. No file over ~300 lines.

## Repo layout

```
web/                  Next.js (App Router, TypeScript, Tailwind)
api/                  FastAPI + LangGraph (Python, uv)
  app/routes/         one file per area: appointments, insurance, chat, handoffs
  app/agent/          LangGraph graph, nodes, tools
  app/rag/            ingestion + retrieval
  tests/
supabase/migrations/  SQL migrations, numbered
scripts/              seed data, fake card generator, ingestion runner
data/                 policies/, contracts/, synthea output
evals/                eval cases and runners
```

## Commands

```
# API
cd api && uv run uvicorn app.main:app --reload --port 8000
cd api && uv run pytest

# Web
cd web && npm run dev
```

## Rules

* All database access goes through Supabase. Schema changes only via files in `supabase/migrations/`, never by hand.
* All times stored in UTC. Convert to local time only in the UI.
* Appointment logic is plain code + SQL. No LLM calls in appointment endpoints.
* In-network checks are a database lookup. The LLM never decides coverage yes/no.
* Never hard-code demo data in app code. Seed data lives in `scripts/` only.
* Secrets only in `.env` (gitignored). Keep `.env.example` up to date.
* Every API endpoint gets at least one pytest test.
* Every file path resolved relative to the file, so scripts run from any folder.
* The agent never gives medical advice or interprets results. When in doubt, hand off.

## Style

* Python: type hints, Pydantic models for request and response bodies.
* TypeScript: strict mode, no `any`.
* UI: minimal hospital style. White background, one accent color, large readable text.
