from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Protocol

from .models import Movie, ScrapeRun, SeatSnapshot, Showing, Theater


SCHEMA = """
create table if not exists theaters (
  id integer primary key autoincrement,
  chain text not null,
  name text not null,
  city text not null,
  external_id text not null unique,
  ticketing_url text not null
);

create table if not exists movies (
  id integer primary key autoincrement,
  normalized_title text not null unique,
  source_title text not null,
  poster_url text,
  rating text,
  runtime_minutes integer
);

create table if not exists showings (
  id integer primary key autoincrement,
  theater_id integer not null references theaters(id),
  movie_id integer not null references movies(id),
  starts_at text not null,
  format text,
  auditorium text,
  ticket_url text not null,
  source_id text not null unique,
  unique(theater_id, movie_id, starts_at, format)
);

create table if not exists seat_snapshots (
  id integer primary key autoincrement,
  showing_id integer not null references showings(id),
  checked_at text not null,
  inferred_occupied integer,
  available_seats integer,
  total_sellable_seats integer,
  raw_status text not null,
  confidence text not null,
  error_message text
);

create table if not exists scrape_runs (
  id integer primary key autoincrement,
  chain text not null,
  started_at text not null,
  finished_at text,
  status text not null,
  count_checked integer not null default 0,
  count_failed integer not null default 0
);
"""


class Repository(Protocol):
    def init_schema(self) -> None: ...
    def upsert_theater(self, theater: Theater) -> str | int: ...
    def upsert_movie(self, movie: Movie) -> str | int: ...
    def upsert_showing(self, showing: Showing) -> str | int: ...
    def insert_snapshot(self, snapshot: SeatSnapshot) -> str | int: ...
    def start_run(self, run: ScrapeRun) -> str | int: ...
    def finish_run(
        self, run_id: str | int, status: str, count_checked: int, count_failed: int
    ) -> None: ...
    def list_screenings(self) -> list[Any]: ...
    def prune_snapshots(self, keep_after_hours: int = 6) -> int: ...


def repository_from_url(database_url: str) -> Repository:
    if database_url.startswith("sqlite:///"):
        return SQLiteRepository(database_url)
    if database_url == "supabase" or database_url.startswith("https://"):
        supabase_url = (
            database_url if database_url.startswith("https://") else os.environ["SUPABASE_URL"]
        )
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        return SupabaseRepository(supabase_url, key)
    raise ValueError(
        "Unsupported database URL. Use sqlite:///path/to.db for local validation "
        "or 'supabase' with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY set."
    )


class SQLiteRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("SQLiteRepository expects a sqlite:/// URL")
        self.path = Path(database_url.removeprefix("sqlite:///"))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def upsert_theater(self, theater: Theater) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                insert into theaters (chain, name, city, external_id, ticketing_url)
                values (?, ?, ?, ?, ?)
                on conflict(external_id) do update set
                  chain=excluded.chain,
                  name=excluded.name,
                  city=excluded.city,
                  ticketing_url=excluded.ticketing_url
                """,
                (
                    theater.chain,
                    theater.name,
                    theater.city,
                    theater.external_id,
                    str(theater.ticketing_url),
                ),
            )
            return _lookup_id(connection, "theaters", "external_id", theater.external_id)

    def upsert_movie(self, movie: Movie) -> int:
        with self.connect() as connection:
            connection.execute(
                """
                insert into movies
                  (normalized_title, source_title, poster_url, rating, runtime_minutes)
                values (?, ?, ?, ?, ?)
                on conflict(normalized_title) do update set
                  source_title=excluded.source_title,
                  poster_url=excluded.poster_url,
                  rating=excluded.rating,
                  runtime_minutes=excluded.runtime_minutes
                """,
                (
                    movie.normalized_title,
                    movie.source_title,
                    str(movie.poster_url) if movie.poster_url else None,
                    movie.rating,
                    movie.runtime_minutes,
                ),
            )
            return _lookup_id(
                connection, "movies", "normalized_title", movie.normalized_title
            )

    def upsert_showing(self, showing: Showing) -> int:
        with self.connect() as connection:
            theater_id = _lookup_id(
                connection, "theaters", "external_id", showing.theater_external_id
            )
            movie_id = _lookup_id(
                connection,
                "movies",
                "normalized_title",
                showing.movie_normalized_title,
            )
            connection.execute(
                """
                insert into showings
                  (theater_id, movie_id, starts_at, format, auditorium, ticket_url, source_id)
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(source_id) do update set
                  starts_at=excluded.starts_at,
                  format=excluded.format,
                  auditorium=excluded.auditorium,
                  ticket_url=excluded.ticket_url
                """,
                (
                    theater_id,
                    movie_id,
                    showing.starts_at.isoformat(),
                    showing.format,
                    showing.auditorium,
                    str(showing.ticket_url),
                    showing.source_id,
                ),
            )
            return _lookup_id(connection, "showings", "source_id", showing.source_id)

    def insert_snapshot(self, snapshot: SeatSnapshot) -> int:
        with self.connect() as connection:
            showing_id = _lookup_id(
                connection, "showings", "source_id", snapshot.showing_source_id
            )
            cursor = connection.execute(
                """
                insert into seat_snapshots
                  (showing_id, checked_at, inferred_occupied, available_seats,
                   total_sellable_seats, raw_status, confidence, error_message)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    showing_id,
                    snapshot.checked_at.isoformat(),
                    snapshot.inferred_occupied,
                    snapshot.available_seats,
                    snapshot.total_sellable_seats,
                    snapshot.raw_status,
                    snapshot.confidence,
                    snapshot.error_message,
                ),
            )
            return int(cursor.lastrowid)

    def start_run(self, run: ScrapeRun) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                insert into scrape_runs
                  (chain, started_at, finished_at, status, count_checked, count_failed)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    run.chain,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status,
                    run.count_checked,
                    run.count_failed,
                ),
            )
            return int(cursor.lastrowid)

    def finish_run(
        self, run_id: int, status: str, count_checked: int, count_failed: int
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                update scrape_runs
                set finished_at=?, status=?, count_checked=?, count_failed=?
                where id=?
                """,
                (
                    datetime.now(UTC).isoformat(),
                    status,
                    count_checked,
                    count_failed,
                    run_id,
                ),
            )

    def list_screenings(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    select
                      s.source_id,
                      m.source_title as movie_title,
                      t.name as theater_name,
                      s.starts_at,
                      latest.inferred_occupied,
                      latest.raw_status,
                      latest.confidence
                    from showings s
                    join movies m on m.id = s.movie_id
                    join theaters t on t.id = s.theater_id
                    left join (
                      select ss.*
                      from seat_snapshots ss
                      join (
                        select showing_id, max(checked_at) as checked_at
                        from seat_snapshots
                        group by showing_id
                      ) newest
                        on newest.showing_id = ss.showing_id
                       and newest.checked_at = ss.checked_at
                    ) latest on latest.showing_id = s.id
                    order by s.starts_at asc
                    """
                )
            )

    def prune_snapshots(self, keep_after_hours: int = 6) -> int:
        # For showings that started more than keep_after_hours ago, delete the
        # snapshot history but keep the latest snapshot and the latest one with
        # seat numbers, so final tickets-sold / seats-available figures per
        # showing survive. Mirrors prune_seat_snapshots() in supabase/schema.sql.
        cutoff = (datetime.now(UTC) - timedelta(hours=keep_after_hours)).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                delete from seat_snapshots
                where showing_id in (
                    select id from showings where datetime(starts_at) < datetime(?)
                  )
                  and exists (
                    select 1 from seat_snapshots newer
                    where newer.showing_id = seat_snapshots.showing_id
                      and (datetime(newer.checked_at) > datetime(seat_snapshots.checked_at)
                        or (datetime(newer.checked_at) = datetime(seat_snapshots.checked_at)
                          and newer.id > seat_snapshots.id))
                  )
                  and (inferred_occupied is null
                    or exists (
                      select 1 from seat_snapshots newer
                      where newer.showing_id = seat_snapshots.showing_id
                        and newer.inferred_occupied is not null
                        and (datetime(newer.checked_at) > datetime(seat_snapshots.checked_at)
                          or (datetime(newer.checked_at) = datetime(seat_snapshots.checked_at)
                            and newer.id > seat_snapshots.id))
                    ))
                """,
                (cutoff,),
            )
            return cursor.rowcount


class SupabaseRepository:
    def __init__(self, supabase_url: str, service_role_key: str) -> None:
        self.base_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key

    def init_schema(self) -> None:
        # Supabase schema is applied with supabase/schema.sql; PostgREST cannot run DDL.
        return None

    def upsert_theater(self, theater: Theater) -> str:
        rows = self._request(
            "POST",
            "theaters",
            query={"on_conflict": "external_id"},
            payload={
                "chain": theater.chain,
                "name": theater.name,
                "city": theater.city,
                "external_id": theater.external_id,
                "ticketing_url": str(theater.ticketing_url),
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]["id"]

    def upsert_movie(self, movie: Movie) -> str:
        rows = self._request(
            "POST",
            "movies",
            query={"on_conflict": "normalized_title"},
            payload={
                "normalized_title": movie.normalized_title,
                "source_title": movie.source_title,
                "poster_url": str(movie.poster_url) if movie.poster_url else None,
                "rating": movie.rating,
                "runtime_minutes": movie.runtime_minutes,
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]["id"]

    def upsert_showing(self, showing: Showing) -> str:
        theater_id = self._lookup_id(
            "theaters", "external_id", showing.theater_external_id
        )
        movie_id = self._lookup_id(
            "movies", "normalized_title", showing.movie_normalized_title
        )
        rows = self._request(
            "POST",
            "showings",
            query={"on_conflict": "source_id"},
            payload={
                "theater_id": theater_id,
                "movie_id": movie_id,
                "starts_at": showing.starts_at.isoformat(),
                "format": showing.format,
                "auditorium": showing.auditorium,
                "ticket_url": str(showing.ticket_url),
                "source_id": showing.source_id,
            },
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0]["id"]

    def insert_snapshot(self, snapshot: SeatSnapshot) -> str:
        showing_id = self._lookup_id(
            "showings", "source_id", snapshot.showing_source_id
        )
        rows = self._request(
            "POST",
            "seat_snapshots",
            payload={
                "showing_id": showing_id,
                "checked_at": snapshot.checked_at.isoformat(),
                "inferred_occupied": snapshot.inferred_occupied,
                "available_seats": snapshot.available_seats,
                "total_sellable_seats": snapshot.total_sellable_seats,
                "raw_status": snapshot.raw_status,
                "confidence": snapshot.confidence,
                "error_message": snapshot.error_message,
            },
            prefer="return=representation",
        )
        return rows[0]["id"]

    def start_run(self, run: ScrapeRun) -> str:
        rows = self._request(
            "POST",
            "scrape_runs",
            payload={
                "chain": run.chain,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "count_checked": run.count_checked,
                "count_failed": run.count_failed,
            },
            prefer="return=representation",
        )
        return rows[0]["id"]

    def finish_run(
        self, run_id: str | int, status: str, count_checked: int, count_failed: int
    ) -> None:
        self._request(
            "PATCH",
            "scrape_runs",
            query={"id": f"eq.{run_id}"},
            payload={
                "finished_at": datetime.now(UTC).isoformat(),
                "status": status,
                "count_checked": count_checked,
                "count_failed": count_failed,
            },
            prefer="return=minimal",
        )

    def list_screenings(self) -> list[dict[str, Any]]:
        return self._request("GET", "solocinema_screenings")

    def prune_snapshots(self, keep_after_hours: int = 6) -> int:
        # Runs the prune_seat_snapshots() database function from
        # supabase/migrations/0003_prune_seat_snapshots.sql.
        rows = self._request(
            "POST",
            "rpc/prune_seat_snapshots",
            payload={"keep_after": f"{keep_after_hours} hours"},
        )
        return int(rows[0]) if rows else 0

    def _lookup_id(self, table: str, column: str, value: str) -> str:
        rows = self._request(
            "GET", table, query={"select": "id", column: f"eq.{value}", "limit": "1"}
        )
        if not rows:
            raise LookupError(f"Could not find {table}.{column}={value}")
        return rows[0]["id"]

    def _request(
        self,
        method: str,
        resource: str,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/rest/v1/{resource}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
        if not content:
            return []
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else [parsed]


def _lookup_id(
    connection: sqlite3.Connection, table: str, column: str, value: str
) -> int:
    row = connection.execute(
        f"select id from {table} where {column} = ?", (value,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Could not find {table}.{column}={value}")
    return int(row["id"])
