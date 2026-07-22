from __future__ import annotations

import http.client
import io
import json
import os
import sqlite3
import urllib.error
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
                      coalesce(latest.raw_status, 'unknown') as raw_status,
                      coalesce(latest.confidence, 'low') as confidence
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
        split = urllib.parse.urlsplit(self.base_url)
        self._host = split.netloc
        self._path_prefix = split.path.rstrip("/")
        self._connection: http.client.HTTPSConnection | None = None
        # Per-run id caches. Rows only ever gain ids; caching them for the
        # lifetime of one collection run avoids the lookup GET that would
        # otherwise follow every upsert.
        self._theater_ids: dict[str, str] = {}
        self._movie_ids: dict[str, str] = {}
        self._showing_ids: dict[str, str] = {}
        self._upserted_payloads: dict[tuple[str, str], str] = {}

    def init_schema(self) -> None:
        # Supabase schema is applied with supabase/schema.sql; PostgREST cannot run DDL.
        return None

    def upsert_theater(self, theater: Theater) -> str:
        payload = {
            "chain": theater.chain,
            "name": theater.name,
            "city": theater.city,
            "external_id": theater.external_id,
            "ticketing_url": str(theater.ticketing_url),
        }
        cached = self._cached_upsert("theaters", theater.external_id, payload)
        if cached is not None:
            return cached
        rows = self._request(
            "POST",
            "theaters",
            query={"on_conflict": "external_id", "select": "id"},
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._remember(
            "theaters", theater.external_id, payload, rows[0]["id"], self._theater_ids
        )

    def upsert_movie(self, movie: Movie) -> str:
        payload = {
            "normalized_title": movie.normalized_title,
            "source_title": movie.source_title,
            "poster_url": str(movie.poster_url) if movie.poster_url else None,
            "rating": movie.rating,
            "runtime_minutes": movie.runtime_minutes,
        }
        cached = self._cached_upsert("movies", movie.normalized_title, payload)
        if cached is not None:
            return cached
        rows = self._request(
            "POST",
            "movies",
            query={"on_conflict": "normalized_title", "select": "id"},
            payload=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self._remember(
            "movies", movie.normalized_title, payload, rows[0]["id"], self._movie_ids
        )

    def upsert_showing(self, showing: Showing) -> str:
        theater_id = self._theater_ids.get(
            showing.theater_external_id
        ) or self._lookup_id("theaters", "external_id", showing.theater_external_id)
        movie_id = self._movie_ids.get(
            showing.movie_normalized_title
        ) or self._lookup_id(
            "movies", "normalized_title", showing.movie_normalized_title
        )
        rows = self._request(
            "POST",
            "showings",
            query={"on_conflict": "source_id", "select": "id"},
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
        self._showing_ids[showing.source_id] = rows[0]["id"]
        return rows[0]["id"]

    def insert_snapshot(self, snapshot: SeatSnapshot) -> str:
        showing_id = self._showing_ids.get(
            snapshot.showing_source_id
        ) or self._lookup_id("showings", "source_id", snapshot.showing_source_id)
        self._request(
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
            prefer="return=minimal",
        )
        return showing_id

    def start_run(self, run: ScrapeRun) -> str:
        rows = self._request(
            "POST",
            "scrape_runs",
            query={"select": "id"},
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

    def _cached_upsert(
        self, table: str, key: str, payload: dict[str, Any]
    ) -> str | None:
        # Skip the network round-trip when this run already upserted an
        # identical row (the same movie appears once per showtime).
        if self._upserted_payloads.get((table, key)) != json.dumps(
            payload, sort_keys=True
        ):
            return None
        cache = self._theater_ids if table == "theaters" else self._movie_ids
        return cache.get(key)

    def _remember(
        self,
        table: str,
        key: str,
        payload: dict[str, Any],
        row_id: str,
        cache: dict[str, str],
    ) -> str:
        self._upserted_payloads[(table, key)] = json.dumps(payload, sort_keys=True)
        cache[key] = row_id
        return row_id

    def _request(
        self,
        method: str,
        resource: str,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        path = f"{self._path_prefix}/rest/v1/{resource}"
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"

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

        # One TLS connection is reused across the whole run; a stale
        # keep-alive socket (server closed between requests) is retried once
        # on a fresh connection. Failures after the request is known to have
        # reached the server are not retried, so writes are never duplicated.
        for attempt in (1, 2):
            connection = self._connection
            if connection is None:
                connection = http.client.HTTPSConnection(self._host, timeout=30)
                self._connection = connection
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                status = response.status
                reason = response.reason
                content = response.read()
            except (
                http.client.RemoteDisconnected,
                http.client.CannotSendRequest,
                BrokenPipeError,
                ConnectionResetError,
            ):
                self._close_connection()
                if attempt == 2:
                    raise
                continue
            except Exception:
                self._close_connection()
                raise
            break

        if status >= 400:
            self._close_connection()
            url = f"https://{self._host}{path}"
            raise urllib.error.HTTPError(
                url, status, reason, response.headers, io.BytesIO(content)
            )
        if not content:
            return []
        parsed = json.loads(content)
        return parsed if isinstance(parsed, list) else [parsed]

    def _close_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None


def _lookup_id(
    connection: sqlite3.Connection, table: str, column: str, value: str
) -> int:
    row = connection.execute(
        f"select id from {table} where {column} = ?", (value,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Could not find {table}.{column}={value}")
    return int(row["id"])
