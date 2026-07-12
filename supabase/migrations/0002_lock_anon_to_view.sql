-- Run this in the Supabase SQL editor against the live database.
-- Locks anonymous access down to the read-only solocinema_screenings view:
-- makes the view definer-rights, drops the permissive base-table read policies,
-- and revokes direct anon access to the base tables. Idempotent.

-- 1. Recreate the screenings view with definer rights (drop security_invoker).
alter view public.solocinema_screenings set (security_invoker = false);

-- 2. Drop the permissive base-table select policies.
drop policy if exists "Public read theaters" on public.theaters;
drop policy if exists "Public read movies" on public.movies;
drop policy if exists "Public read showings" on public.showings;
drop policy if exists "Public read seat snapshots" on public.seat_snapshots;

-- 3. Revoke every table privilege the anon/authenticated roles hold in public,
-- including Supabase's default INSERT/UPDATE/DELETE/TRUNCATE grants (TRUNCATE
-- is not governed by RLS), then stop future tables from getting those grants.
revoke all on all tables in schema public from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;

-- 4. Ensure anon can still read through the view.
grant usage on schema public to anon;
grant select on public.solocinema_screenings to anon;
