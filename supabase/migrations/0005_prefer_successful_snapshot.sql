-- Apply through the Supabase Management API (or the SQL editor).
-- The board shows each showing's most recent snapshot, and a probe that
-- failed also writes one (raw_status 'failed', no seat numbers). A single
-- transient failure therefore blanked a showing's good seat count until the
-- next successful run — which can be hours when GitHub drops scheduled runs.
-- Prefer the newest snapshot that isn't a failure; a showing whose every
-- snapshot failed still shows as failed. checked_at is still that snapshot's,
-- so the board's freshness handling sees how old the count really is.
-- Same columns, so create or replace keeps the view's definer rights and the
-- anon grant from 0002. Idempotent.

create or replace view public.solocinema_screenings as
select
  s.id::text as showing_id,
  m.source_title as movie_title,
  t.name as theater_name,
  t.chain,
  s.starts_at,
  s.format,
  s.ticket_url,
  latest.inferred_occupied,
  latest.available_seats,
  latest.total_sellable_seats,
  coalesce(latest.raw_status, 'unknown') as raw_status,
  coalesce(latest.confidence, 'low') as confidence,
  latest.checked_at
from public.showings s
join public.movies m on m.id = s.movie_id
join public.theaters t on t.id = s.theater_id
left join lateral (
  select ss.*
  from public.seat_snapshots ss
  where ss.showing_id = s.id
  order by (ss.raw_status = 'failed'), ss.checked_at desc
  limit 1
) latest on true
where s.starts_at >= now() - interval '30 minutes';
