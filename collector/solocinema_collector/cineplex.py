from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .landmark import normalize_movie_title
from .models import Movie, ScrapeRun, SeatParseResult, SeatSnapshot, Showing, Theater
from .storage import Repository, repository_from_url
from .url_guard import require_allowed_url


CINEPLEX_API_BASE = "https://apis.cineplex.com/prod"
CINEPLEX_SUBSCRIPTION_KEY = os.environ.get("CINEPLEX_SUBSCRIPTION_KEY")
CINEPLEX_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REGINA_TZ = ZoneInfo("America/Regina")
# Seat sales for regular showings barely move more than a couple of days out
# (see docs/imax-research.md's probe-window analysis), so only open seat maps
# for showings starting within this many Regina calendar days.
DEFAULT_PROBE_DAYS = 3

CINEPLEX_REGINA_THEATERS = {
    "4108": Theater(
        chain="Cineplex",
        name="Cineplex Cinemas Southland",
        city="Regina",
        external_id="cineplex-southland",
        ticketing_url="https://www.cineplex.com/theatre/cineplex-cinemas-southland",
    ),
    "4114": Theater(
        chain="Cineplex",
        name="Cineplex Cinemas Normanview",
        city="Regina",
        external_id="cineplex-normanview",
        ticketing_url="https://www.cineplex.com/theatre/cineplex-cinemas-normanview",
    ),
}

TITLE_KEYS = {
    "title",
    "name",
    "movietitle",
    "movie_title",
    "film_title",
    "filmtitle",
    "event_title",
    "eventtitle",
}
SHOWTIME_ID_KEYS = {
    "vistasessionid",
    "vista_session_id",
    "sessionid",
    "session_id",
    "showtimeid",
    "showtime_id",
}
START_KEYS = {
    "startsat",
    "starts_at",
    "starttime",
    "start_time",
    "datetime",
    "date_time",
    "showtime",
    "show_time",
    "showdatetime",
    "show_date_time",
    "showstartdatetime",
    "show_start_date_time",
    "showstartdatetimeutc",
    "show_start_date_time_utc",
}
DATE_KEYS = {"date", "startdate", "start_date", "showdate", "show_date", "businessdate", "business_date"}
TIME_KEYS = {"time", "starttime", "start_time", "showtime", "show_time"}
FORMAT_KEYS = {
    "format",
    "formatname",
    "format_name",
    "experiencetypes",
    "experience_types",
    "experience",
    "experiencename",
    "experience_name",
    "presentation",
    "presentationtype",
    "presentation_type",
}
AUDITORIUM_KEYS = {"auditorium", "auditoriumname", "auditorium_name", "screen", "screenname"}
ONLINE_KEYS = {
    "isonlineticketingenabled",
    "is_online_ticketing_enabled",
    "isshowtimeenabledonline",
    "is_showtime_enabled_online",
    "onlineenabled",
    "online_enabled",
    "isticketingenabled",
    "is_ticketing_enabled",
    "isavailableforpurchase",
    "is_available_for_purchase",
}
URL_KEYS = {
    "ticketingurl",
    "ticketing_url",
    "ticketingredesignurl",
    "ticketing_redesign_url",
    "deeplinkurl",
    "deeplink_url",
    "seatmapurl",
    "seat_map_url",
}
RESERVED_KEYS = {
    "isreservedseating",
    "is_reserved_seating",
    "reservedseating",
    "reserved_seating",
    "isallocatedseating",
    "is_allocated_seating",
}
SEAT_STATE_KEYS = {"status", "seatstatus", "seat_status", "availability", "state"}
SEAT_ID_KEYS = {
    "id",
    "seatid",
    "seat_id",
    "seatnumber",
    "seat_number",
    "seatlabel",
    "seat_label",
    "gridseatnum",
    "grid_seat_num",
}
AVAILABLE_TERMS = {"available", "open", "free", "selectable"}
OCCUPIED_TERMS = {"occupied", "sold", "reserved", "unavailable", "taken", "held", "hold"}
BROKEN_TERMS = {"broken", "blocked", "house", "maintenance", "lock", "locked"}


@dataclass(frozen=True)
class CineplexShowing:
    movie_title: str
    starts_at: datetime
    ticket_url: str
    source_id: str
    vista_session_id: str
    location_id: str
    theater_external_id: str
    format: str | None = None
    auditorium: str | None = None
    is_online_ticketing_enabled: bool | None = None
    is_reserved_seating: bool | None = None


@dataclass(frozen=True)
class CineplexCollectionSummary:
    discovered: int
    checked: int
    failed: int
    database_url: str
    status: str


def discover_cineplex_showings(
    location_id: str = "4108",
    subscription_key: str | None = CINEPLEX_SUBSCRIPTION_KEY,
) -> list[CineplexShowing]:
    payload = _open_json(_showtimes_url(location_id), subscription_key=subscription_key)
    theater = theater_for_location(location_id)
    return extract_cineplex_showings(payload, location_id, theater.external_id)


def extract_cineplex_showings(
    payload: Any,
    location_id: str,
    theater_external_id: str,
    now: datetime | None = None,
) -> list[CineplexShowing]:
    showings = _walk_showtimes(
        payload,
        context={},
        location_id=location_id,
        theater_external_id=theater_external_id,
        now=now or datetime.now(REGINA_TZ),
    )
    deduped: dict[str, CineplexShowing] = {}
    for showing in showings:
        deduped.setdefault(showing.source_id, showing)
    return sorted(deduped.values(), key=lambda item: (item.starts_at, item.movie_title))


def probe_cineplex_seat_map(
    showing: CineplexShowing,
    subscription_key: str | None = CINEPLEX_SUBSCRIPTION_KEY,
) -> SeatParseResult:
    layout = _open_json(
        _seat_layout_url(showing.location_id, showing.vista_session_id),
        subscription_key=subscription_key,
    )
    availability = _open_json(
        _seat_availability_url(showing.location_id, showing.vista_session_id),
        subscription_key=subscription_key,
    )
    return parse_cineplex_seat_responses(layout, availability)


def parse_cineplex_seat_responses(layout: Any, availability: Any) -> SeatParseResult:
    seats = _seat_identities(layout)
    states = _seat_states(availability)
    identities = sorted(seats | set(states))
    if not identities:
        return SeatParseResult(
            inferred_occupied=None,
            available_seats=None,
            total_sellable_seats=None,
            raw_status="unknown",
            confidence="low",
            error_message="No Cineplex seat records found",
        )

    counts = {"available": 0, "occupied": 0, "blocked": 0, "unknown": 0}
    for identity in identities:
        state = states.get(identity, "unknown")
        counts[state if state in counts else "unknown"] += 1

    inferred_occupied = counts["occupied"] + counts["blocked"]
    unknown_ratio = counts["unknown"] / len(identities)
    confidence = "high"
    if counts["blocked"] or unknown_ratio > 0:
        confidence = "medium"
    if unknown_ratio >= 0.15:
        confidence = "low"

    return SeatParseResult(
        inferred_occupied=inferred_occupied,
        available_seats=counts["available"],
        total_sellable_seats=len(identities),
        raw_status="available",
        confidence=confidence,
        unknown_seats=counts["unknown"],
        blocked_seats=counts["blocked"],
    )


def run_cineplex_collection(
    database_url: str,
    location_ids: list[str] | None = None,
    max_showings: int | None = None,
    probe_seats: bool = True,
    probe_days: int = DEFAULT_PROBE_DAYS,
    subscription_key: str | None = CINEPLEX_SUBSCRIPTION_KEY,
) -> CineplexCollectionSummary:
    showings: list[CineplexShowing] = []
    for location_id in location_ids or list(CINEPLEX_REGINA_THEATERS):
        showings.extend(discover_cineplex_showings(location_id, subscription_key=subscription_key))
    if max_showings is not None:
        showings = showings[:max_showings]

    probe_until = (
        datetime.now(REGINA_TZ).date() + timedelta(days=probe_days - 1)
        if probe_days > 0
        else None
    )
    repository = repository_from_url(database_url)
    repository.init_schema()
    return write_cineplex_showings(
        repository,
        showings,
        database_url=database_url,
        probe_seats=probe_seats and probe_days > 0,
        probe_until=probe_until,
        subscription_key=subscription_key,
    )


def write_cineplex_showings(
    repository: Repository,
    showings: list[CineplexShowing],
    database_url: str,
    probe_seats: bool = True,
    probe_until: date | None = None,
    subscription_key: str | None = CINEPLEX_SUBSCRIPTION_KEY,
) -> CineplexCollectionSummary:
    run_id = repository.start_run(ScrapeRun(chain="Cineplex"))
    checked = 0
    failed = 0

    try:
        for theater in _theaters_for_showings(showings):
            repository.upsert_theater(theater)
        for showing in showings:
            checked += 1
            try:
                repository.upsert_movie(
                    Movie(
                        normalized_title=normalize_movie_title(showing.movie_title),
                        source_title=showing.movie_title,
                    )
                )
                repository.upsert_showing(
                    Showing(
                        theater_external_id=showing.theater_external_id,
                        movie_normalized_title=normalize_movie_title(showing.movie_title),
                        starts_at=showing.starts_at,
                        format=showing.format,
                        auditorium=showing.auditorium,
                        ticket_url=showing.ticket_url,
                        source_id=showing.source_id,
                    )
                )
                parsed = _unknown_result("Seat probe skipped")
                if probe_seats and not _can_probe_seats(showing):
                    parsed = _unknown_result("Cineplex showing is not online reserved seating")
                elif probe_seats and not _within_probe_window(showing, probe_until):
                    parsed = _unknown_result(
                        f"Seat probe deferred (showing is after {probe_until})"
                    )
                elif probe_seats:
                    parsed = probe_cineplex_seat_map(showing, subscription_key=subscription_key)
                repository.insert_snapshot(_snapshot_from_result(showing, parsed))
            except Exception as error:
                failed += 1
                _insert_failed_snapshot(repository, showing, error)

        status = _run_status(checked, failed)
        repository.finish_run(run_id, status, count_checked=checked, count_failed=failed)
        return CineplexCollectionSummary(
            discovered=len(showings),
            checked=checked,
            failed=failed,
            database_url=database_url,
            status=status,
        )
    except Exception:
        repository.finish_run(run_id, "failed", count_checked=checked, count_failed=max(failed, 1))
        raise


def theater_for_location(location_id: str) -> Theater:
    theater = CINEPLEX_REGINA_THEATERS.get(str(location_id))
    if theater:
        return theater
    return Theater(
        chain="Cineplex",
        name=f"Cineplex {location_id}",
        city="Regina",
        external_id=f"cineplex-{location_id}",
        ticketing_url="https://www.cineplex.com",
    )


def summary_to_json(summary: CineplexCollectionSummary) -> str:
    return json.dumps(asdict(summary), indent=2)


def showings_to_json(showings: list[CineplexShowing]) -> str:
    return json.dumps([_showing_to_dict(showing) for showing in showings], indent=2)


def _walk_showtimes(
    value: Any,
    context: dict[str, Any],
    location_id: str,
    theater_external_id: str,
    now: datetime,
) -> list[CineplexShowing]:
    discovered: list[CineplexShowing] = []
    if isinstance(value, dict):
        current = dict(context)
        title = _title_from_dict(value)
        if title and not _looks_like_showtime(value):
            current["movie_title"] = title
        format_value = _format_from_value(value)
        if format_value and not _looks_like_showtime(value):
            current["format"] = format_value
        date_value = _first_raw(value, DATE_KEYS)
        if date_value:
            current["date"] = date_value

        if _looks_like_showtime(value):
            movie_title = _title_from_dict(value) or current.get("movie_title")
            starts_at = _starts_at_from_dict(value, current.get("date"), now)
            vista_session_id = _first_text(value, SHOWTIME_ID_KEYS)
            if movie_title and starts_at and vista_session_id:
                discovered.append(
                    CineplexShowing(
                        movie_title=movie_title,
                        starts_at=starts_at,
                        ticket_url=_first_text(value, URL_KEYS) or _ticket_url(location_id, vista_session_id),
                        source_id=f"{theater_external_id}-cineplex-{vista_session_id}",
                        vista_session_id=vista_session_id,
                        location_id=location_id,
                        theater_external_id=theater_external_id,
                        format=_format_from_value(value) or current.get("format"),
                        auditorium=_first_text(value, AUDITORIUM_KEYS),
                        is_online_ticketing_enabled=_optional_bool(value, ONLINE_KEYS),
                        is_reserved_seating=_optional_bool(value, RESERVED_KEYS),
                    )
                )

        for child in value.values():
            discovered.extend(
                _walk_showtimes(child, current, location_id, theater_external_id, now)
            )
    elif isinstance(value, list):
        for child in value:
            discovered.extend(
                _walk_showtimes(child, context, location_id, theater_external_id, now)
            )
    return discovered


def _looks_like_showtime(value: dict[str, Any]) -> bool:
    keys = {_norm_key(key) for key in value}
    return bool(keys & SHOWTIME_ID_KEYS) and bool(keys & (START_KEYS | TIME_KEYS))


def _title_from_dict(value: dict[str, Any]) -> str | None:
    title = _first_text(value, TITLE_KEYS)
    if title:
        return title
    movie = value.get("movie") or value.get("film") or value.get("event")
    if isinstance(movie, dict):
        return _translatable_text(movie.get("title")) or _translatable_text(movie.get("name"))
    return None


def _starts_at_from_dict(
    value: dict[str, Any], context_date: Any | None, now: datetime
) -> datetime | None:
    for key, raw in value.items():
        if _norm_key(key) in START_KEYS:
            if context_date:
                parsed = _parse_datetime(f"{context_date} {raw}", now=now)
                if parsed:
                    return parsed
            parsed = _parse_datetime(raw, now=now)
            if parsed:
                return parsed
    date_value = _first_raw(value, DATE_KEYS) or context_date
    time_value = _first_raw(value, TIME_KEYS)
    if date_value and time_value:
        return _parse_datetime(f"{date_value} {time_value}", now=now)
    return None


def _parse_datetime(raw: Any, now: datetime) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed = None
    if parsed:
        return _as_utc(parsed)

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
    )
    for fmt in formats:
        try:
            return _as_utc(datetime.strptime(text, fmt).replace(tzinfo=REGINA_TZ))
        except ValueError:
            continue

    time_only = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", text, re.IGNORECASE)
    if time_only:
        local = datetime.combine(
            now.date(),
            datetime.strptime(time_only.group(1).upper(), "%I:%M %p").time(),
            REGINA_TZ,
        )
        return _as_utc(local)
    return None


def _seat_identities(value: Any) -> set[str]:
    identities: set[str] = set()
    for seat in _walk_seat_objects(value, require_state=False):
        identity = _seat_identity(seat)
        if identity:
            identities.add(identity)
    return identities


def _seat_states(value: Any) -> dict[str, str]:
    states: dict[str, str] = {}
    if isinstance(value, dict):
        raw_map = value.get("seatAvailabilities") or value.get("seat_availabilities")
        if isinstance(raw_map, dict):
            for identity, state in raw_map.items():
                states[str(identity)] = _classify_cineplex_state(state)
    for seat in _walk_seat_objects(value, require_state=True):
        identity = _seat_identity(seat)
        if identity:
            states[identity] = _classify_cineplex_seat(seat)
    return states


def _walk_seat_objects(value: Any, require_state: bool):
    if isinstance(value, dict):
        keys = {_norm_key(key) for key in value}
        has_identity = bool(keys & SEAT_ID_KEYS)
        has_state = bool(keys & SEAT_STATE_KEYS) or any(
            key in keys for key in ("isavailable", "is_available", "isavailabletosell")
        )
        if has_identity and (has_state or not require_state):
            yield value
        for child in value.values():
            yield from _walk_seat_objects(child, require_state=require_state)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_seat_objects(child, require_state=require_state)


def _seat_identity(seat: dict[str, Any]) -> str | None:
    explicit = _first_text(seat, SEAT_ID_KEYS)
    if explicit:
        return explicit
    position = seat.get("position") or seat.get("Position")
    if isinstance(position, dict):
        area = _first_text(position, {"areanumber", "area_number"})
        row = _first_text(position, {"rownumber", "row_number"})
        column = _first_text(position, {"columnnumber", "column_number"})
        if area and row and column:
            return f"{area}:{row}:{column}"
    row_label = _first_text(seat, {"rowlabel", "row_label", "row"})
    seat_label = _first_text(seat, {"seatlabel", "seat_label", "seat", "number"})
    if row_label and seat_label:
        return f"{row_label}{seat_label}"
    return None


def _classify_cineplex_seat(seat: dict[str, Any]) -> str:
    for key, raw in seat.items():
        normalized = _norm_key(key)
        if isinstance(raw, bool) and normalized in {"isavailable", "is_available", "isavailabletosell"}:
            return "available" if raw else "occupied"

    tokens: set[str] = set()
    for key, raw in seat.items():
        if _norm_key(key) in SEAT_STATE_KEYS:
            tokens.update(_tokenize(raw))
    return _classify_tokens(tokens)


def _classify_cineplex_state(value: Any) -> str:
    return _classify_tokens(_tokenize(value))


def _classify_tokens(tokens: set[str]) -> str:
    if tokens & AVAILABLE_TERMS:
        return "available"
    if tokens & BROKEN_TERMS:
        return "blocked"
    if tokens & OCCUPIED_TERMS:
        return "occupied"
    return "unknown"


def _format_from_value(value: dict[str, Any]) -> str | None:
    raw = _first_raw(value, FORMAT_KEYS)
    if isinstance(raw, list):
        values = [_translatable_text(item) for item in raw]
        return ", ".join(item for item in values if item) or None
    if isinstance(raw, dict):
        return _translatable_text(raw)
    return str(raw).strip() if raw else None


def _theaters_for_showings(showings: list[CineplexShowing]) -> list[Theater]:
    by_external_id: dict[str, Theater] = {}
    for showing in showings:
        theater = theater_for_location(showing.location_id)
        by_external_id[theater.external_id] = theater
    return list(by_external_id.values())


def _snapshot_from_result(showing: CineplexShowing, parsed: SeatParseResult) -> SeatSnapshot:
    return SeatSnapshot(
        showing_source_id=showing.source_id,
        inferred_occupied=parsed.inferred_occupied,
        available_seats=parsed.available_seats,
        total_sellable_seats=parsed.total_sellable_seats,
        raw_status=parsed.raw_status,
        confidence=parsed.confidence,
        error_message=parsed.error_message,
    )


def _insert_failed_snapshot(
    repository: Repository, showing: CineplexShowing, error: Exception
) -> None:
    try:
        repository.insert_snapshot(
            SeatSnapshot(
                showing_source_id=showing.source_id,
                inferred_occupied=None,
                available_seats=None,
                total_sellable_seats=None,
                raw_status="failed",
                confidence="low",
                error_message=str(error),
            )
        )
    except Exception:
        return


def _unknown_result(message: str) -> SeatParseResult:
    return SeatParseResult(
        inferred_occupied=None,
        available_seats=None,
        total_sellable_seats=None,
        raw_status="unknown",
        confidence="low",
        error_message=message,
    )


def _within_probe_window(showing: CineplexShowing, probe_until: date | None) -> bool:
    if probe_until is None:
        return True
    return showing.starts_at.astimezone(REGINA_TZ).date() <= probe_until


def _can_probe_seats(showing: CineplexShowing) -> bool:
    if showing.is_online_ticketing_enabled is False:
        return False
    if showing.is_reserved_seating is False:
        return False
    return True


def _run_status(checked: int, failed: int) -> str:
    if checked == 0:
        return "failed"
    if failed == 0:
        return "success"
    if failed < checked:
        return "partial"
    return "failed"


def _open_json(url: str, subscription_key: str | None) -> Any:
    if not subscription_key:
        raise RuntimeError("CINEPLEX_SUBSCRIPTION_KEY is not set")
    require_allowed_url(url)
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Ocp-Apim-Subscription-Key": subscription_key,
            "User-Agent": CINEPLEX_USER_AGENT,
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, errors="replace"))


def _showtimes_url(location_id: str) -> str:
    query = urlencode({"language": "en", "locationId": location_id})
    return f"{CINEPLEX_API_BASE}/cpx/theatrical/api/v1/showtimes?{query}"


def _seat_layout_url(location_id: str, vista_session_id: str) -> str:
    return (
        f"{CINEPLEX_API_BASE}/ticketing/api/v1/theatre/{location_id}"
        f"/showtime/{vista_session_id}/seat-layout"
    )


def _seat_availability_url(location_id: str, vista_session_id: str) -> str:
    return (
        f"{CINEPLEX_API_BASE}/ticketing/api/v1/theatre/{location_id}"
        f"/showtime/{vista_session_id}/seat-availability?preview=true"
    )


def _ticket_url(location_id: str, vista_session_id: str) -> str:
    return f"https://www.cineplex.com/ticketing/{location_id}/{vista_session_id}"


def _first_text(value: dict[str, Any], keys: set[str]) -> str | None:
    raw = _first_raw(value, keys)
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _translatable_text(raw)
    text = str(raw).strip()
    return text or None


def _first_raw(value: dict[str, Any], keys: set[str]) -> Any | None:
    normalized = {_norm_key(key): raw for key, raw in value.items()}
    for key in keys:
        raw = normalized.get(_norm_key(key))
        if raw not in (None, ""):
            return raw
    return None


def _optional_bool(value: dict[str, Any], keys: set[str]) -> bool | None:
    raw = _first_raw(value, keys)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _translatable_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        for key in ("text", "name", "title", "value"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _tokenize(value: Any) -> set[str]:
    text = str(value).replace("_", " ").replace("-", " ").lower()
    return {part.strip() for part in text.split() if part.strip()}


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", key.replace("-", "_").lower())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=REGINA_TZ)
    return value.astimezone(UTC)


def _showing_to_dict(showing: CineplexShowing) -> dict[str, Any]:
    data = asdict(showing)
    data["starts_at"] = showing.starts_at.isoformat()
    return data
