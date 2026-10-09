-- Phase 2: login profiles + lock the browser out of the tables.
--
-- The browser only ever talks to the FastAPI backend. The backend connects as the
-- database owner (DATABASE_URL), which bypasses row-level security, so it keeps
-- working. Supabase's public keys (anon / authenticated) get nothing.
-- Phase 3 adds policies where Realtime needs them.

create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  role          text not null
                constraint profiles_role_check check (role in ('patient', 'staff')),
  patient_id    uuid unique references public.patients (id),
  display_name  text not null,
  -- Patients must be linked to a patient record; staff must not be.
  constraint profiles_patient_link check ((role = 'patient') = (patient_id is not null))
);

-- Row-level security on, no policies: anon/authenticated can read and write nothing.
alter table public.patients     enable row level security;
alter table public.doctors      enable row level security;
alter table public.slots        enable row level security;
alter table public.appointments enable row level security;
alter table public.profiles     enable row level security;

-- Supabase exposes public functions over its REST API by default. Only the backend
-- may book, cancel or reschedule.
revoke execute on function public.book_slot(uuid, uuid)
  from public, anon, authenticated;
revoke execute on function public.cancel_appointment(uuid, uuid)
  from public, anon, authenticated;
revoke execute on function public.reschedule_appointment(uuid, uuid, uuid)
  from public, anon, authenticated;
