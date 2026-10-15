# Concierge AI: Spec

## Problem
Hospital call centers are flooded with routine requests: appointments, insurance
questions, prep instructions, "what were my results". Patients wait on hold, staff burn
out. Concierge AI handles routine requests in a patient portal and hands anything
urgent to a human, live.

All patient data is synthetic (Synthea). No real PHI anywhere.

## Users and screens
**Patient portal** (Next.js, after login), three tabs:
1. **Documents**: upload insurance card photo or referral PDF, see what was extracted, check coverage
2. **Appointments**: view, book, reschedule, cancel
3. **Ask**: chat with the AI assistant

**Staff inbox** (Next.js, staff login): live list of handoff tickets. Staff can join a
patient's chat, reply, and close the ticket.

Design: clean, minimal, hospital-style. White background, one accent color, large
readable text, no decoration.

## Core flows

### 1. Appointments (deterministic, NO AI)
- Each doctor has slots per day. A slot is open when it is in the future and has no
  `booked` appointment (the `open_slots` view). Slots have no status column.
- View: patient's upcoming and past appointments.
- Book: pick doctor and visit type, see open future slots, pick one.
- Reschedule: show open future slots for the same doctor and visit type; swap in one
  database transaction (old slot released, new slot booked).
- Cancel: release the slot.
- Rules: never show slots in the past. A slot can never be double-booked (enforced by a
  database constraint, not app code).

### 2. Insurance check (multimodal + RAG)
1. Patient uploads a card photo; file saved to Supabase Storage.
2. Vision model (Groq `qwen/qwen3.8-27b`) extracts: payer, plan name, member name, member ID,
   group number. A field it can't read is null, never guessed.
3. Patient reviews and confirms the fields (they can edit them).
4. In-network check is a **database lookup** in `network_contracts`, matched in plain code
   (case/space-insensitive + aliases in data/payers.json): in_network, out_of_network or
   not_on_file. Never the LLM. A card whose name isn't the patient's gets a warning.
5. Coverage questions in Ask go to the `check_my_coverage` tool, which takes the patient's
   latest **confirmed** insurance (patient id from the login):
   - none confirmed: tell them to upload and confirm their card in Documents;
   - out of network or not on file: say so plainly and point to billing;
   - in network: RAG over THAT payer's contract chunks only (payer from the database
     match, never the LLM), answered with citations.
   After confirming, Documents shows "Ask about my coverage": it opens Ask with a
   suggested question in the box (not sent until the patient presses Send).
6. Answers state the plan's terms directly, with no per-answer disclaimer. The Ask box
   carries one standing note: answers are written by AI, may contain mistakes, and
   coverage and costs should be checked with the insurer.
   Coverage and copay questions are administrative for the safety check; advice framed
   around insurance ("should I skip the MRI since it isn't covered") is clinical.

### 3. Ask (chat agent, LangGraph)
```
message -> safety check -> agent (LLM + read-only tools, max 4 calls) -> answer citing sources
```
- Safety check runs first on every message (see Handoff).
- Tools: appointments, documents, lab results (grouped by test), record lists (meds,
  conditions, allergies, immunizations, visits), record search, hospital policy search,
  coverage check (`check_my_coverage`, see Insurance check). The patient id is injected
  from the login, never the LLM.
- Answers cite tool lines by tag; the cited sources are saved with the message
  (`messages.sources`) and shown under the reply.
- RAG sources: the patient's own records + hospital policy docs + their payer's contract.
- Never interprets results, never gives medical advice. Reports only what the records say.

### 4. Handoff (the ONLY human-in-the-loop step)
- Life-threatening language (chest pain, can't breathe, suicide, etc.): show a
  "Call 911 now" banner immediately, then also start a handoff. Never make them wait.
- Urgent, clinical, or "I want to talk to someone": the agent pauses (LangGraph
  `interrupt`), creates a `handoffs` row with reason + AI-written summary, and tells the
  patient "Connecting you to a nurse...".
- Staff inbox shows the ticket live (Supabase Realtime). Staff clicks Join, messages
  appear in the patient's chat labeled with the staff name. Agent stays silent.
- Staff clicks Close: agent resumes, transcript saved.
- The patient can press "Back to the assistant" at any time (a nurse may never have
  joined, or has gone): the ticket closes the same way, with a notice in the chat.

## Stack
- Frontend: Next.js (App Router, TypeScript, Tailwind)
- Backend: FastAPI (Python, uv), LangGraph
- Database: Supabase (Postgres, pgvector, Storage, Auth, Realtime, row-level security)
- Embeddings: `BAAI/bge-small-en-v1.5` (384 dims, local)
- Reranker: `BAAI/bge-reranker-base` (local)
- LLM: Groq (text). Vision model chosen in Phase 5.
- Tracing: LangSmith

## Data model
```
profiles           id (auth user), role ('patient'|'staff'), patient_id, display_name
patients           id, synthea_id, first_name, last_name, birth_date
doctors            id, name, specialty
slots              id, doctor_id, start_at (UTC), end_at, visit_type
                   unique (doctor_id, start_at)
open_slots (view)  slots in the future with no 'booked' appointment
appointments       id, patient_id, slot_id (unique while active), status ('booked'|'cancelled'), created_at
network_contracts  id, payer, plan_name, in_network (bool), notes; unique (payer, plan_name)
                   seeded from data/payers.json: FICTIONAL payers, each standing in for a Synthea payer
patient_insurance  id, patient_id, payer (null until read or typed; required when confirmed), plan_name,
                   member_name, member_id, group_number, card_path (Storage),
                   status ('extracted'|'confirmed'), created_at
documents          id, patient_id, kind ('insurance_card'|'referral'), storage_path, created_at,
                   original_filename (sanitized, max 200), content_type (jpeg|png|pdf), size_bytes (<= 10 MB)
                   file in private Storage bucket patient-docs at <patient_id>/<document_id>.<ext>
chunks             id, source_id (stable source key, unique), content, embedding vector(384),
                   source_type ('policy'|'record'|'contract'), patient_id (records only), payer
                   (contract chunks only), doc_title, section, date, sensitive (bool), content_hash
conversations      id, patient_id, status ('bot'|'handoff'|'closed'), created_at
messages           id, conversation_id, sender ('patient'|'assistant'|'staff'), staff_id, sources (jsonb),
                   kind ('text'|'emergency'|'handoff'|'notice', how the UI shows it), content, created_at
                   deleting a conversation also deletes its LangGraph state (trigger)
handoffs           id, conversation_id, reason ('emergency'|'clinical'|'wants_human'), summary,
                   status ('open'|'active'|'closed'), staff_id, trace_id (LangSmith run), created_at, closed_at
                   at most one open/active handoff per conversation (partial unique index)
```
Schema `langgraph`: LangGraph's Postgres checkpointer (graph state per conversation,
thread id = conversation id). Its tables are created and upgraded by the library's
`setup()`; only the schema comes from a migration. Never exposed to the browser.

Row-level security: a patient can read only rows with their own `patient_id`. Staff can
read handoffs, conversations, messages.

## RAG design
**Ingest** (script, re-runnable):
- Policy docs (`data/policies/*.md`): split by heading, ~400 tokens, 50 overlap, keep the heading in the chunk.
- Insurance contract docs (`data/contracts/<payer-slug>.md`, fictional): same, `source_type = 'contract'`,
  tagged with `payer`; searched one payer at a time, never mixed into hospital policy search.
- Patient records (Synthea FHIR): one chunk per event (one lab, one med, one visit),
  date and type written into the text. Last 3 years only, except ongoing items (active
  conditions, allergies and prescriptions), which are kept whatever their start date.
- Mental health and substance-use records tagged `sensitive = true`.
- Skip re-embedding when `content_hash` is unchanged.

**Query**:
embed question -> exact pgvector search with filters (this patient's records OR policy docs;
contract questions filter by payer; exclude sensitive) -> top 25 -> rerank -> top 5 ->
LLM answers only from those 5, citing each. Exact search, no vector index: filters leave a
few hundred rows (sub-millisecond), and an HNSW index applies filters after its search and
can return nothing (evals/compare_vector_search.py). Shown records newest first.

## Data to create
- Synthea patients (reuse existing generator), ~20 patients, payers included
- 8 doctors, slots for the next 30 days generated relative to today
- 5 to 8 hospital policy docs (prep instructions, visiting hours, billing, records requests)
- Contract docs for 4 to 5 payers (copays, prior auth rules, covered services)
- 1 out-of-network payer, to show the "not covered" path
- Fake insurance card images generated by script (clearly marked SAMPLE)

## Build phases
Each phase is one Claude Code session. Each ends with a test the human runs, then a commit.

| Phase | Build | Done when |
|---|---|---|
| 0 | Folder skeleton, Next.js app, FastAPI /health, .env.example, README run steps | both apps start locally |
| 1 | Schema migrations, seed scripts, appointment endpoints + pytest | curl can book, cancel, reschedule; past slots never returned; double-booking rejected |
| 2 | Supabase Auth login, patient portal shell, Appointments tab | log in as demo patient and do all appointment actions by clicking |
| 3 | LangGraph skeleton (safety check, router, appointment tool), Ask tab, handoff + staff inbox with Realtime, LangSmith env vars on | "I need to talk to someone" creates a ticket that staff can join and close |
| 4 | Policy docs, ingestion script, retrieval + rerank, plug into graph | cited answers for "my last A1c?" and "do I fast before blood work?" |
| 5 | Card images, Storage upload, vision extraction, confirm step, network check, contract RAG | upload a card and get in-network + copay with a source; out-of-network card says so |
| 6 | Eval sets (safety, RAG, insurance), GitHub Actions gate | CI fails if escalation recall < 100% |
| 7 | LangSmith dashboards, README, demo script | ready to record |

## Out of scope
Real EHR integration, real PHI, payments, refills, voice, mobile app, multi-hospital support.
