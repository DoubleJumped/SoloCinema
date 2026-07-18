-- Run this in the Supabase SQL editor against the live database.
-- seat_snapshots grows by one row per showing every 15 minutes and is never
-- cleaned up. This adds prune_seat_snapshots(), which the collector calls at
-- the end of each run: for showings that started more than `keep_after` ago it
-- deletes the snapshot history but always keeps
--   * the showing's latest snapshot, and
--   * its latest snapshot that actually has seat numbers (in case the final
--     probe failed),
-- so the final tickets-sold / seats-available figures per showing (and per
-- movie, via joins) are preserved permanently. Idempotent.

create or replace function public.prune_seat_snapshots(
  keep_after interval default interval '6 hours'
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted integer;
begin
  delete from public.seat_snapshots ss
  where ss.showing_id in (
      select s.id from public.showings s
      where s.starts_at < now() - keep_after
    )
    -- not the showing's latest snapshot...
    and exists (
      select 1 from public.seat_snapshots newer
      where newer.showing_id = ss.showing_id
        and (newer.checked_at > ss.checked_at
          or (newer.checked_at = ss.checked_at and newer.id > ss.id))
    )
    -- ...and not its latest snapshot that carries seat numbers
    and (ss.inferred_occupied is null
      or exists (
        select 1 from public.seat_snapshots newer
        where newer.showing_id = ss.showing_id
          and newer.inferred_occupied is not null
          and (newer.checked_at > ss.checked_at
            or (newer.checked_at = ss.checked_at and newer.id > ss.id))
      ));
  get diagnostics deleted = row_count;
  return deleted;
end;
$$;

-- Only the collector (service role) may prune; anon stays read-only.
revoke all on function public.prune_seat_snapshots(interval) from public;
revoke all on function public.prune_seat_snapshots(interval) from anon, authenticated;
grant execute on function public.prune_seat_snapshots(interval) to service_role;
