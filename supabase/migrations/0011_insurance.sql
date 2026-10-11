-- Phase 5 step 1: insurance data. Payers are fictional (data/payers.json), each standing
-- in for a payer in the Synthea data; no real insurer's name or terms are used.

-- Which plans the hospital is in network with. The in-network check is a lookup here,
-- never the LLM. Seeded by scripts/seed.py from data/payers.json.
create table public.network_contracts (
  id          uuid primary key default gen_random_uuid(),
  payer       text not null,
  plan_name   text not null,
  in_network  boolean not null,
  notes       text,
  constraint network_contracts_payer_plan_key unique (payer, plan_name)
);

-- A patient's insurance as read from an uploaded card (step 2), then confirmed by them.
create table public.patient_insurance (
  id            uuid primary key default gen_random_uuid(),
  patient_id    uuid not null references public.patients (id) on delete cascade,
  payer         text not null,
  plan_name     text,
  member_id     text,
  group_number  text,
  card_path     text,  -- the card image in Storage (bucket patient-docs)
  status        text not null default 'extracted'
                constraint patient_insurance_status_check check (status in ('extracted', 'confirmed')),
  created_at    timestamptz not null default now()
);

create index patient_insurance_patient_idx on public.patient_insurance (patient_id, created_at desc);

alter table public.network_contracts enable row level security;
alter table public.patient_insurance enable row level security;

-- Insurer contract docs are their own kind of chunk, tagged with their payer, so hospital
-- policy search never returns insurer terms.
alter table public.chunks drop constraint chunks_source_type_check;
alter table public.chunks add constraint chunks_source_type_check
  check (source_type in ('policy', 'record', 'contract'));
alter table public.chunks add constraint chunks_contract_payer
  check ((source_type = 'contract') = (payer is not null));
