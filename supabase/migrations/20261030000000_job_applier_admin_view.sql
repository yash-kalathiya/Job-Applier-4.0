-- Everyone who signed in to Job Applier 4.0.
create or replace view public.v_job_applier_users as
select
  a.user_id                                                     as id,
  u.email,
  coalesce(nullif(a.profile->>'name', ''), u.raw_user_meta_data->>'full_name', u.raw_user_meta_data->>'name') as name,
  u.raw_app_meta_data->>'provider'                              as provider,
  u.created_at                                                  as joined_at,
  greatest(u.last_sign_in_at, a.updated_at, s.last_application) as last_active,
  nullif(a.profile->>'school', '')                              as school,
  nullif(a.profile->>'major', '')                               as major,
  nullif(a.profile->'search'->>'kind', '')                      as looking_for,
  nullif(a.profile->'search'->>'season', '')                    as season,
  coalesce(a.profile->'search'->'roles', '[]'::jsonb)           as roles,
  (a.vault ? 'experience')                                      as has_resume,
  coalesce(s.applied, 0)                                        as applied,
  coalesce(s.needs_user, 0)                                     as needs_user,
  coalesce(s.total, 0)                                          as applications,
  s.last_application
from public.job_applier_accounts a
join auth.users u on u.id = a.user_id
left join lateral (
  select count(*) filter (where status = 'Applied')     as applied,
         count(*) filter (where status = 'Needs User')  as needs_user,
         count(*)                                       as total,
         max(created_at)                                as last_application
  from public.job_applier_applications x where x.user_id = a.user_id
) s on true;

revoke all on public.v_job_applier_users from anon, authenticated, public;
grant select on public.v_job_applier_users to service_role;
