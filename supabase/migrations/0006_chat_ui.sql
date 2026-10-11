-- Phase 3 step 2: what the Ask tab needs.

-- How a message is shown. Set by the backend from the safety check, so a reloaded
-- conversation keeps its red (emergency) and amber (handoff) messages.
alter table public.messages
  add column kind text not null default 'text'
  constraint messages_kind_check check (kind in ('text', 'emergency', 'handoff'));

-- Deleting a conversation also deletes its LangGraph state. The library owns the
-- tables in the langgraph schema and may add more, so this clears every table there
-- with a thread_id column (thread id = conversation id) instead of naming them.
-- security definer: callers like the service role have no rights on that schema.
create function langgraph.delete_thread_state() returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  t record;
begin
  for t in
    select c.table_name
    from information_schema.columns c
    where c.table_schema = 'langgraph' and c.column_name = 'thread_id'
  loop
    execute format('delete from langgraph.%I where thread_id = $1', t.table_name)
      using old.id::text;
  end loop;
  return old;
end;
$$;

revoke all on function langgraph.delete_thread_state() from public, anon, authenticated;

create trigger conversations_delete_thread_state
  after delete on public.conversations
  for each row execute function langgraph.delete_thread_state();
