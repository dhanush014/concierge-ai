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

**Web** (Next.js, http://localhost:3000):

```bash
cd web
npm install
npm run dev
```
