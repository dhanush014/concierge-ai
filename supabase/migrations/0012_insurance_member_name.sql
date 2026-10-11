-- Phase 5 step 2: the member name printed on the card, so the name check (does the card
-- belong to the logged-in patient?) can be shown again after the card is read.
alter table public.patient_insurance add column member_name text;
