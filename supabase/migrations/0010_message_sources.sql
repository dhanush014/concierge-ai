-- Phase 4 step 3: the sources an assistant answer cites, shown under the reply.
-- A JSON array of {"kind": "record"|"policy", "title", "section", "date"}, in citation
-- order; null for messages without sources.

alter table public.messages add column sources jsonb;
