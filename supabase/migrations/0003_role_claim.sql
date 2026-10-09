-- Phase 2: put the user's role into every access token as the `user_role` claim.
--
-- profiles.role stays the single source of truth. Supabase Auth calls this hook
-- each time it issues a token, so the web app can route patients and staff without
-- reading profiles (which row-level security hides from the browser).
-- Pattern from Supabase's "Custom Claims & RBAC" guide.

create function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
  v_claims jsonb := event -> 'claims';
  v_role text;
begin
  select role into v_role
  from public.profiles
  where id = (event ->> 'user_id')::uuid;

  -- null when the user has no profile; the web app treats that as "no access".
  v_claims := jsonb_set(v_claims, '{user_role}', coalesce(to_jsonb(v_role), 'null'::jsonb));
  return jsonb_set(event, '{claims}', v_claims);
end;
$$;

-- Only Supabase Auth may run the hook.
grant usage on schema public to supabase_auth_admin;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb)
  from public, anon, authenticated;

-- Supabase Auth needs to read profiles (row-level security is on). Nobody else can.
grant select on table public.profiles to supabase_auth_admin;
create policy "auth admin reads profiles for token hook"
  on public.profiles
  as permissive for select
  to supabase_auth_admin
  using (true);
