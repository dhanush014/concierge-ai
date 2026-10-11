-- Phase 5 step 2: a card read can come back without a payer (unreadable -> null, never
-- guessed). Only a confirmed row must have one; the patient fills it in before confirming.
alter table public.patient_insurance alter column payer drop not null;
alter table public.patient_insurance add constraint patient_insurance_confirmed_payer
  check (status <> 'confirmed' or payer is not null);
