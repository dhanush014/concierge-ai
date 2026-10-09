# Concierge AI

Read `SPEC.md` before starting any phase. Build only the phase you were asked for, then stop and explain how to verify it.

## Layout
- `web/` — Next.js (App Router, TypeScript, Tailwind). npm.
- `api/` — FastAPI + LangGraph. Python deps via `uv` only (`uv add`, never pip).
- `supabase/migrations/` — SQL migrations.
- `scripts/` — seed data, ingestion, fake cards.
- `evals/` — agent evals.

## Rules
- Secrets live in `.env` (gitignored). Add new keys to `.env.example` with no values.
- After each change: commit and push to `origin main`.
