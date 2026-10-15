-- The patient can leave a handoff before any staff member joins it, so a closed
-- ticket may have no staff. Open: never staff; active: always staff.
alter table public.handoffs drop constraint handoffs_staff_link;
alter table public.handoffs add constraint handoffs_staff_link check (
  (status = 'open' and staff_id is null)
  or (status = 'active' and staff_id is not null)
  or status = 'closed'
);
