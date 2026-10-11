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

**RAG ingestion** (policy docs in `data/policies/`, contract docs in `data/contracts/` + patient records, embedded locally with
`BAAI/bge-small-en-v1.5`; needs the seed run first):

```bash
uv run --project api scripts/ingest.py --only all   # or: policies | contracts | records
```

Re-runnable: unchanged chunks aren't embedded again, chunks whose source is gone are removed.

Retrieval evals (real models, local; run after ingesting):

```bash
uv run --project api evals/run_retrieval.py          # hit@5 / rank, with and without reranker
```

```bash
uv run --project api evals/compare_vector_search.py  # exact vs HNSW index
```

```bash
uv run --project api evals/run_answers.py   # real Groq LLM: correct + cited, tools used
```

```bash
uv run --project api evals/run_safety.py    # real Groq LLM: escalation recall, over-escalation
```

```bash
uv run --project api evals/run_extraction.py   # real vision model on data/cards/: field accuracy
```

```bash
uv run --project api evals/run_coverage.py   # real Groq LLM: contract facts per payer, never another payer's plan
```

`run_coverage.py` creates temporary patients with confirmed insurance and deletes them when
it finishes.
The first run downloads the model (~130 MB) if it isn't cached. Checkable policy facts for
later tests: `evals/policy_facts.json`.

**Insurance demo data.** Payers are fictional (`data/payers.json`), each standing in for a
payer in the Synthea data; 5 are in network, 1 is not. `uv run scripts/seed.py --network-only`
refreshes `network_contracts` without touching anything else. Sample cards (all marked SAMPLE)
and their true field values (`data/cards/truth.json`):

```bash
uv run --project api scripts/make_cards.py
```

Note: a full `scripts/seed.py` resets patients and everything that hangs off them (documents,
conversations, chunks); re-run the ingestion afterwards.

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

**Chat agent** (needs `GROQ_API_KEY` in `.env`; LangSmith tracing is on when the
`LANGSMITH_*` values are set). With a token in `$TOKEN` from the step above:

```bash
curl -N http://localhost:8000/me/chat -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"message": "when is my next appointment?"}'
```

You get a stream of `data: {...}` lines: `conversation` (its id), `token` pieces of the
reply, then `done` with the safety category and route. Send `"conversation_id"` to
continue a chat; `GET /me/conversations/<id>` returns its saved messages. The API tests
use a fake model and never call Groq.

**Web** (Next.js, http://localhost:3000). Reads the `NEXT_PUBLIC_*` values from the root `.env`.
Sign in with a demo login printed by the seed script: patients land on `/portal`, staff on `/staff`.

**Live handoff demo.** Open two browsers: a patient (`aja.casper@…`) on **Ask** and staff
(`nurse.kim@…`) on the **Staff inbox**. "I need to talk to someone" pauses the agent and the
ticket appears in the inbox live; Join, reply, Close, and the patient sees each step live
(Supabase Realtime). While waiting for a nurse the agent is silent, except an emergency still
gets the 911 message. "View trace" shows when the `LANGSMITH_*` values are set.

**Agent graph.** The diagram is in [docs/agent-graph.md](docs/agent-graph.md) (regenerate with
`cd api && uv run python -m app.agent.draw`; a test fails if it's stale). To step through
the graph in LangGraph Studio (needs `supabase start`; fake LLM unless `GROQ_API_KEY` is set):

```bash
cd api && uv run langgraph dev
```

It opens Studio in the browser (free LangSmith login). Patient id goes in the context panel;
empty means Aja. Studio keeps its own memory and doesn't write handoffs to the database.

**End-to-end tests** (Playwright; needs `supabase start` and the seed run once):

```bash
cd web
npx playwright install chromium   # first time only
npm run test:e2e
```

They start the API and web servers if needed, create their own "Dr. E2E …" doctor and slots,
and delete them afterwards (leftovers from a crashed run are removed at the start).

The API runs with a **fake LLM** in E2E (`LLM_FAKE=1 APP_ENV=local`): free, repeatable
replies that repeat the tool's records back. If an API is already running on :8000 with the
real model, the run stops with "not in fake LLM mode"; stop that API first. `LLM_FAKE=1`
without `APP_ENV=local` makes the API refuse to start, and fake mode logs a loud warning.
`GET /health` shows which one is running (`"llm": "groq"` or `"fake"`).

```bash
cd web
npm install
npm run dev
```
