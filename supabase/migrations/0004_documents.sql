-- Phase 2.5: patient documents (insurance card photos, referral PDFs). Storage only.
--
-- Files live in the private Storage bucket "patient-docs" at
-- <patient_id>/<document_id>.<ext>. The browser never touches the bucket or this
-- table directly: the FastAPI backend uploads, lists, signs and deletes.

create table public.documents (
  id                 uuid primary key default gen_random_uuid(),
  patient_id         uuid not null references public.patients (id),
  kind               text not null
                     constraint documents_kind_check check (kind in ('insurance_card', 'referral')),
  storage_path       text not null unique,
  original_filename  text not null
                     constraint documents_filename_length check (char_length(original_filename) between 1 and 200),
  content_type       text not null
                     constraint documents_content_type_check
                     check (content_type in ('image/jpeg', 'image/png', 'application/pdf')),
  size_bytes         integer not null
                     constraint documents_size_check check (size_bytes between 1 and 10485760),
  created_at         timestamptz not null default now()
);

create index documents_patient_created_idx on public.documents (patient_id, created_at desc);

-- Row-level security on, no policies: anon/authenticated get nothing.
alter table public.documents enable row level security;

-- Private bucket. The limits repeat the API's checks as a second line of defence.
-- storage.objects already has row-level security on; with no policies for this
-- bucket, only the service role (the backend) can read or write it.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'patient-docs',
  'patient-docs',
  false,
  10485760,
  array['image/jpeg', 'image/png', 'application/pdf']
);
