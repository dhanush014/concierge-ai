-- Phase 3 step 3: live handoff to staff.

create table public.handoffs (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  reason           text not null
                   constraint handoffs_reason_check check (reason in ('emergency', 'clinical', 'wants_human')),
  summary          text not null,
  status           text not null default 'open'
                   constraint handoffs_status_check check (status in ('open', 'active', 'closed')),
  staff_id         uuid references public.profiles (id),
  trace_id         text,  -- LangSmith run id of the turn that started the handoff
  created_at       timestamptz not null default now(),
  closed_at        timestamptz,
  -- Open = nobody has joined yet; active/closed = the staff member who joined.
  constraint handoffs_staff_link check ((status = 'open') = (staff_id is null)),
  constraint handoffs_closed_at check ((status = 'closed') = (closed_at is not null))
);

-- At most one open or active handoff per conversation, even if two requests race.
create unique index handoffs_one_live_per_conversation
  on public.handoffs (conversation_id) where status in ('open', 'active');
create index handoffs_status_created_idx on public.handoffs (status, created_at desc);

alter table public.handoffs enable row level security;

-- Notices: "Nurse Kim joined the chat", "The assistant is back", "A nurse has been notified".
alter table public.messages drop constraint messages_kind_check;
alter table public.messages add constraint messages_kind_check
  check (kind in ('text', 'emergency', 'handoff', 'notice'));

-- Read-only policies so Supabase Realtime can deliver rows to the browser. All writes
-- still go through the API (no insert/update/delete policies).
-- Helpers are security definer because profiles is hidden by its own RLS, and live in
-- a schema the REST API doesn't serve.
create schema private;
grant usage on schema private to authenticated;

create function private.my_patient_id() returns uuid
language sql stable security definer set search_path = ''
as $$ select patient_id from public.profiles where id = auth.uid() $$;

create function private.is_staff() returns boolean
language sql stable security definer set search_path = ''
as $$ select exists (select 1 from public.profiles where id = auth.uid() and role = 'staff') $$;

revoke all on function private.my_patient_id() from public, anon;
revoke all on function private.is_staff() from public, anon;
grant execute on function private.my_patient_id() to authenticated;
grant execute on function private.is_staff() to authenticated;

create policy "patients read own conversations" on public.conversations
  for select to authenticated
  using (patient_id = private.my_patient_id());

create policy "staff read handoff conversations" on public.conversations
  for select to authenticated
  using (private.is_staff() and exists (
    select 1 from public.handoffs h where h.conversation_id = conversations.id));

create policy "patients read own messages" on public.messages
  for select to authenticated
  using (exists (
    select 1 from public.conversations c
    where c.id = messages.conversation_id and c.patient_id = private.my_patient_id()));

create policy "staff read handoff messages" on public.messages
  for select to authenticated
  using (private.is_staff() and exists (
    select 1 from public.handoffs h where h.conversation_id = messages.conversation_id));

create policy "staff read handoffs" on public.handoffs
  for select to authenticated
  using (private.is_staff());

alter publication supabase_realtime add table public.messages, public.conversations, public.handoffs;
