-- Phase 4 step 1: RAG chunks (hospital policy docs + patient records), embedded locally
-- with BAAI/bge-small-en-v1.5 (384 dims, normalized). Written by scripts/ingest.py.

create extension if not exists vector with schema extensions;

create table public.chunks (
  id            uuid primary key default gen_random_uuid(),
  -- Stable key of what the chunk came from, e.g. "policy:billing.md#Payment plans#0" or
  -- "fhir:Observation/<id>". Lets a re-run tell an edited chunk from a deleted one.
  source_id     text not null unique,
  source_type   text not null constraint chunks_source_type_check check (source_type in ('policy', 'record')),
  patient_id    uuid references public.patients (id) on delete cascade,
  payer         text,          -- contract docs only (Phase 5)
  doc_title     text not null, -- policy: document title; record: event type ("Lab result")
  section       text,          -- policy: heading path; record: item name
  date          date,          -- record: event date; policy: null
  sensitive     boolean not null default false,
  content       text not null,
  content_hash  text not null, -- sha256 of model name + content; unchanged = not re-embedded
  embedding     extensions.vector(384) not null,
  created_at    timestamptz not null default now(),
  -- Records belong to a patient; policies to nobody.
  constraint chunks_patient_link check ((source_type = 'record') = (patient_id is not null))
);

create index chunks_embedding_idx on public.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index chunks_patient_idx on public.chunks (patient_id);
create index chunks_source_type_idx on public.chunks (source_type);

-- Read only by the backend (retrieval in step 2). No browser access.
alter table public.chunks enable row level security;
