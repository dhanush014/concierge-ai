-- A reply can carry one action button, e.g. "Review and book" with the booking page
-- prefilled ({"label": ..., "href": ...}). The chat opens it; the patient confirms.
alter table public.messages add column action jsonb;
