-- Job Applier 4.0: tables prefixed job_applier_, one private storage bucket "job_applier".

create table if not exists public.job_applier_accounts (
  user_id uuid primary key references auth.users(id) on delete cascade,
  profile jsonb not null default '{}'::jsonb,       -- contact, school, search prefs, apply policy
  vault jsonb not null default '{}'::jsonb,         -- the Career Vault
  answers jsonb not null default '[]'::jsonb,       -- application answer bank
  learnings jsonb not null default '{}'::jsonb,     -- preferences + outcome learning
  updated_at timestamptz not null default now()
);

create table if not exists public.job_applier_applications (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade default auth.uid(),
  job_key text not null,
  company text, title text, url text, ats text,
  status text not null,
  resume_path text,                                 -- object path in the job_applier bucket
  notes text,
  created_at timestamptz not null default now()
);
create index if not exists job_applier_applications_user on public.job_applier_applications(user_id, created_at desc);

alter table public.job_applier_accounts enable row level security;
alter table public.job_applier_applications enable row level security;

drop policy if exists "own account" on public.job_applier_accounts;
create policy "own account" on public.job_applier_accounts for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "own applications" on public.job_applier_applications;
create policy "own applications" on public.job_applier_applications for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- private bucket; objects live under <user_id>/...
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('job_applier', 'job_applier', false, 10485760, array['application/pdf', 'application/x-tex', 'text/plain', 'application/json'])
on conflict (id) do nothing;

drop policy if exists "job_applier own files read" on storage.objects;
create policy "job_applier own files read" on storage.objects for select to authenticated
  using (bucket_id = 'job_applier' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "job_applier own files write" on storage.objects;
create policy "job_applier own files write" on storage.objects for insert to authenticated
  with check (bucket_id = 'job_applier' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "job_applier own files update" on storage.objects;
create policy "job_applier own files update" on storage.objects for update to authenticated
  using (bucket_id = 'job_applier' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists "job_applier own files delete" on storage.objects;
create policy "job_applier own files delete" on storage.objects for delete to authenticated
  using (bucket_id = 'job_applier' and (storage.foldername(name))[1] = auth.uid()::text);

grant select, insert, update, delete on public.job_applier_accounts to authenticated;
grant select, insert, update, delete on public.job_applier_applications to authenticated;
grant usage, select on sequence public.job_applier_applications_id_seq to authenticated;
