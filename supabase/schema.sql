create table if not exists public.theaters (
  id uuid primary key default gen_random_uuid(),
  chain text not null check (chain in ('Landmark', 'Cineplex', 'Other')),
  name text not null,
  city text not null default 'Regina',
  external_id text not null unique,
  ticketing_url text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.movies (
  id uuid primary key default gen_random_uuid(),
  normalized_title text not null unique,
  source_title text not null,
  poster_url text,
  rating text,
  runtime_minutes integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.showings (
  id uuid primary key default gen_random_uuid(),
  theater_id uuid not null references public.theaters(id) on delete cascade,
  movie_id uuid not null references public.movies(id) on delete cascade,
  starts_at timestamptz not null,
  format text,
  auditorium text,
  ticket_url text not null,
  source_id text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(theater_id, movie_id, starts_at, format)
);

create table if not exists public.seat_snapshots (
  id uuid primary key default gen_random_uuid(),
  showing_id uuid not null references public.showings(id) on delete cascade,
  checked_at timestamptz not null default now(),
  inferred_occupied integer,
  available_seats integer,
  total_sellable_seats integer,
  raw_status text not null check (raw_status in ('available', 'unknown', 'failed', 'unavailable')),
  confidence text not null check (confidence in ('high', 'medium', 'low')),
  error_message text
);

create table if not exists public.scrape_runs (
  id uuid primary key default gen_random_uuid(),
  chain text not null check (chain in ('Landmark', 'Cineplex', 'Other')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null check (status in ('running', 'success', 'partial', 'failed')),
  count_checked integer not null default 0,
  count_failed integer not null default 0
);

create index if not exists showings_starts_at_idx on public.showings(starts_at);
create index if not exists showings_movie_id_idx on public.showings(movie_id);
create index if not exists seat_snapshots_showing_checked_idx
  on public.seat_snapshots(showing_id, checked_at desc);

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
  order by ss.checked_at desc
  limit 1
) latest on true
where s.starts_at >= now() - interval '30 minutes';

alter table public.theaters enable row level security;
alter table public.movies enable row level security;
alter table public.showings enable row level security;
alter table public.seat_snapshots enable row level security;
alter table public.scrape_runs enable row level security;

-- Anon reads only through the definer-rights view above; the base tables have
-- RLS enabled with no anon policies, so direct table access returns nothing.
-- The collector writes with the service-role key, which bypasses RLS.
grant usage on schema public to anon;
grant select on public.solocinema_screenings to anon;

-- Called by the collector after each run. For showings that started more than
-- `keep_after` ago, deletes the snapshot history but always keeps the latest
-- snapshot and the latest one with seat numbers, so final tickets-sold /
-- seats-available figures per showing survive permanently.
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
    and exists (
      select 1 from public.seat_snapshots newer
      where newer.showing_id = ss.showing_id
        and (newer.checked_at > ss.checked_at
          or (newer.checked_at = ss.checked_at and newer.id > ss.id))
    )
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

revoke all on function public.prune_seat_snapshots(interval) from public;
revoke all on function public.prune_seat_snapshots(interval) from anon, authenticated;
grant execute on function public.prune_seat_snapshots(interval) to service_role;
