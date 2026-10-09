-- Phase 1: appointments schema.
--
-- All times are timestamptz (stored as UTC).
-- A slot has no status column. It is "open" when it is in the future and has no
-- appointment with status 'booked' (see the open_slots view). The partial unique
-- index on appointments is what makes double-booking impossible.
--
-- Errors use PostgREST's PTxxx SQLSTATEs, so an RPC call returns that HTTP status:
--   PT404 not found, PT403 someone else's appointment, PT409 state conflict,
--   PT422 request not allowed (past slot, wrong doctor or visit type).

-- Tables ---------------------------------------------------------------------

create table public.patients (
  id          uuid primary key default gen_random_uuid(),
  synthea_id  text not null unique,
  first_name  text not null,
  last_name   text not null,
  birth_date  date not null
);

create table public.doctors (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  specialty  text not null
);

create table public.slots (
  id          uuid primary key default gen_random_uuid(),
  doctor_id   uuid not null references public.doctors (id),
  start_at    timestamptz not null,
  end_at      timestamptz not null,
  visit_type  text not null,
  constraint slots_end_after_start check (end_at > start_at),
  -- Also serves as the (doctor_id, start_at) lookup index.
  constraint slots_doctor_start_unique unique (doctor_id, start_at)
);

create table public.appointments (
  id          uuid primary key default gen_random_uuid(),
  patient_id  uuid not null references public.patients (id),
  slot_id     uuid not null references public.slots (id),
  status      text not null default 'booked'
              constraint appointments_status_check check (status in ('booked', 'cancelled')),
  created_at  timestamptz not null default now()
);

-- Indexes --------------------------------------------------------------------

-- A slot can have at most one booked appointment. Cancelled rows don't count.
create unique index appointments_one_booked_per_slot
  on public.appointments (slot_id)
  where status = 'booked';

create index appointments_patient_id_idx on public.appointments (patient_id);

-- Views ----------------------------------------------------------------------

create view public.open_slots
with (security_invoker = true) as
select s.id, s.doctor_id, s.start_at, s.end_at, s.visit_type
from public.slots s
where s.start_at > now()
  and not exists (
    select 1
    from public.appointments a
    where a.slot_id = s.id
      and a.status = 'booked'
  );

-- Functions (each call runs in a single transaction) -------------------------

create function public.book_slot(p_patient_id uuid, p_slot_id uuid)
returns public.appointments
language plpgsql
set search_path = ''
as $$
declare
  v_slot public.slots;
  v_appt public.appointments;
begin
  -- Lock the slot so concurrent bookings of it run one at a time.
  select * into v_slot from public.slots where id = p_slot_id for update;

  if not found then
    raise exception 'slot_not_found' using errcode = 'PT404';
  end if;
  if v_slot.start_at <= now() then
    raise exception 'slot_in_past' using errcode = 'PT422';
  end if;
  if exists (
    select 1 from public.appointments
    where slot_id = p_slot_id and status = 'booked'
  ) then
    raise exception 'slot_not_open' using errcode = 'PT409';
  end if;

  insert into public.appointments (patient_id, slot_id)
  values (p_patient_id, p_slot_id)
  returning * into v_appt;

  return v_appt;
end;
$$;

create function public.cancel_appointment(p_appointment_id uuid, p_patient_id uuid)
returns public.appointments
language plpgsql
set search_path = ''
as $$
declare
  v_appt public.appointments;
  v_start timestamptz;
begin
  select * into v_appt from public.appointments where id = p_appointment_id for update;

  if not found then
    raise exception 'appointment_not_found' using errcode = 'PT404';
  end if;
  if v_appt.patient_id <> p_patient_id then
    raise exception 'not_your_appointment' using errcode = 'PT403';
  end if;
  if v_appt.status <> 'booked' then
    raise exception 'appointment_not_booked' using errcode = 'PT409';
  end if;

  select start_at into v_start from public.slots where id = v_appt.slot_id;
  if v_start <= now() then
    raise exception 'appointment_in_past' using errcode = 'PT422';
  end if;

  update public.appointments
  set status = 'cancelled'
  where id = p_appointment_id
  returning * into v_appt;

  return v_appt;
end;
$$;

-- Cancels the old appointment and books the new slot as a new appointment row.
-- Any error after the cancel rolls the cancel back too.
create function public.reschedule_appointment(
  p_appointment_id uuid,
  p_patient_id uuid,
  p_new_slot_id uuid
)
returns public.appointments
language plpgsql
set search_path = ''
as $$
declare
  v_old public.appointments;
  v_old_slot public.slots;
  v_new_slot public.slots;
begin
  -- Ownership, status and past checks happen here.
  v_old := public.cancel_appointment(p_appointment_id, p_patient_id);

  if v_old.slot_id = p_new_slot_id then
    raise exception 'same_slot' using errcode = 'PT422';
  end if;

  select * into v_old_slot from public.slots where id = v_old.slot_id;
  select * into v_new_slot from public.slots where id = p_new_slot_id;

  if found and (
    v_new_slot.doctor_id <> v_old_slot.doctor_id
    or v_new_slot.visit_type <> v_old_slot.visit_type
  ) then
    raise exception 'slot_mismatch' using errcode = 'PT422',
      detail = 'New slot must be the same doctor and visit type.';
  end if;

  -- Not-found, past and not-open checks for the new slot happen here.
  return public.book_slot(p_patient_id, p_new_slot_id);
end;
$$;
