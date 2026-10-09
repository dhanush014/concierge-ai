# Concierge AI

Patient front-office AI assistant.

## Run locally

Prereqs: Node 20+, [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # then fill in values
```

**API** (FastAPI, http://localhost:8000):

```bash
cd api
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Check: `curl http://localhost:8000/health` → `{"status":"ok"}`

**Database** (local Supabase, needs Docker running):

```bash
supabase start            # from the repo root
supabase db reset         # rebuild schema from supabase/migrations
uv run scripts/seed.py    # 20 patients, 8 doctors, slots for today ±30 days
```

Reseed before a demo: slots and "upcoming" appointments are relative to the day you seed.

**Tests** (API, against local Supabase; they create and delete their own data):

```bash
cd api && uv run pytest
```

API docs: http://localhost:8000/docs. Until login exists (Phase 2), send `X-Patient-Id`
with a patient id printed by the seed script.

**Web** (Next.js, http://localhost:3000):

```bash
cd web
npm install
npm run dev
```
