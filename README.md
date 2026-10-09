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

API docs: http://localhost:8000/docs. Patient routes need a Supabase access token.
The seed script creates demo logins (password is `DEMO_PASSWORD` in `.env`). Get a token:

```bash
set -a; source .env; set +a
curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"aja.casper@demo.concierge.test\",\"password\":\"$DEMO_PASSWORD\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
```

Paste it into **Authorize** on the docs page.

**Web** (Next.js, http://localhost:3000). Reads the `NEXT_PUBLIC_*` values from the root `.env`.
Sign in with a demo login printed by the seed script: patients land on `/portal`, staff on `/staff`.

**End-to-end tests** (Playwright; needs `supabase start` and the seed run once):

```bash
cd web
npx playwright install chromium   # first time only
npm run test:e2e
```

They start the API and web servers if needed, create their own "Dr. E2E …" doctor and slots,
and delete them afterwards (leftovers from a crashed run are removed at the start).

```bash
cd web
npm install
npm run dev
```
