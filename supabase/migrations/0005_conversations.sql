-- Phase 3 step 1: chat conversations and messages.
--
-- The backend writes both tables. RLS on, no policies yet: anon/authenticated get
-- nothing. Phase 3.3 adds the policies Realtime needs for the staff inbox.

create table public.conversations (
  id          uuid primary key default gen_random_uuid(),
  patient_id  uuid not null references public.patients (id),
  status      text not null default 'bot'
              constraint conversations_status_check check (status in ('bot', 'handoff', 'closed')),
  created_at  timestamptz not null default now()
);

create index conversations_patient_created_idx on public.conversations (patient_id, created_at desc);

create table public.messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  sender           text not null
                   constraint messages_sender_check check (sender in ('patient', 'assistant', 'staff')),
  staff_id         uuid references public.profiles (id),
  content          text not null
                   constraint messages_content_length check (char_length(content) between 1 and 8000),
  created_at       timestamptz not null default now(),
  -- Staff messages name their author; nobody else has one.
  constraint messages_staff_link check ((sender = 'staff') = (staff_id is not null))
);

create index messages_conversation_created_idx on public.messages (conversation_id, created_at);

alter table public.conversations enable row level security;
alter table public.messages      enable row level security;

-- LangGraph's Postgres checkpointer keeps graph state here (needed to pause the graph
-- for handoff in 3.3). The library creates and upgrades its own tables in this schema
-- via setup() at API startup; only the schema itself is ours. Not exposed to the
-- browser: Supabase's REST API only serves the public schema, and the browser roles
-- get no access.
create schema langgraph;
revoke all on schema langgraph from public, anon, authenticated;
