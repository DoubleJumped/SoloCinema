-- Run this in the Supabase SQL editor against the live database.
-- The 0003 version of prune_seat_snapshots() deletes every prunable row in a
-- single statement, with two correlated EXISTS probes per candidate row. It
-- has timed out (57014, surfaced as HTTP 500) on every collector run since it
-- shipped, so seat_snapshots never shrank (~266k rows by 2026-08-18) and each
-- retry only got slower. This replaces it with a batched version: one call
-- computes the per-showing keeper snapshots once, deletes at most `max_rows`
-- of the rest, and returns the count. The collector calls it in a loop until
-- a call comes back short, so the backlog drains across a run and steady
-- state is one cheap call. Keeper semantics are unchanged: for showings that
-- started more than `keep_after` ago, the latest snapshot and the latest
-- snapshot with seat numbers survive permanently. Idempotent.

-- Signature changes (extra parameter), so drop the old overload first —
-- otherwise PostgREST sees two candidates and rejects the RPC as ambiguous.
drop function if exists public.prune_seat_snapshots(interval);

create function public.prune_seat_snapshots(
  keep_after interval default interval '6 hours',
  max_rows integer default 20000
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted integer;
begin
  with old_snapshots as (
    select ss.id, ss.showing_id, ss.checked_at, ss.inferred_occupied
    from public.seat_snapshots ss
    join public.showings s on s.id = ss.showing_id
    where s.starts_at < now() - keep_after
  ),
  keepers as (
    (select distinct on (showing_id) id
     from old_snapshots
     order by showing_id, checked_at desc, id desc)
    union
    (select distinct on (showing_id) id
     from old_snapshots
     where inferred_occupied is not null
     order by showing_id, checked_at desc, id desc)
  ),
  victims as (
    select id from old_snapshots
    where id not in (select id from keepers)
    limit max_rows
  )
  delete from public.seat_snapshots ss
  using victims
  where ss.id = victims.id;
  get diagnostics deleted = row_count;
  return deleted;
end;
$$;

-- Only the collector (service role) may prune; anon stays read-only.
revoke all on function public.prune_seat_snapshots(interval, integer) from public;
revoke all on function public.prune_seat_snapshots(interval, integer)
  from anon, authenticated;
grant execute on function public.prune_seat_snapshots(interval, integer)
  to service_role;
