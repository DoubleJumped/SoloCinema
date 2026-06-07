from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from .atom import AtomShowing, discover_atom_showings, probe_atom_checkout_seat_map
from .models import Movie, ScrapeRun, SeatParseResult, SeatSnapshot, Showing, Theater
from .playwright_probe import probe_seat_map
from .storage import Repository, repository_from_url


LANDMARK_REGINA_URL = "https://as.landmarkcinemas.com/showtimes/regina"
LANDMARK_REGINA_EXTERNAL_ID = "landmark-regina"
REGINA_TZ = ZoneInfo("America/Regina")
LANDMARK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

LANDMARK_REGINA_THEATER = Theater(
    chain="Landmark",
    name="Landmark Cinemas 8 Regina",
    city="Regina",
    external_id=LANDMARK_REGINA_EXTERNAL_ID,
    ticketing_url=LANDMARK_REGINA_URL,
)

MOVIE_TITLE_KEYS = {
    "movietitle",
    "movie_title",
    "moviename",
    "movie_name",
    "filmtitle",
    "film_title",
    "filmname",
    "film_name",
    "eventtitle",
    "event_title",
    "showtitle",
    "show_title",
}
FALLBACK_TITLE_KEYS = {"title", "name"}
START_KEYS = {
    "startsat",
    "starts_at",
    "starttime",
    "start_time",
    "showtime",
    "show_time",
    "showdatetime",
    "show_date_time",
    "performancedatetime",
    "performance_date_time",
    "sessiondatetime",
    "session_date_time",
    "datetime",
    "date_time",
}
DATE_KEYS = {"date", "showdate", "show_date", "businessdate", "business_date"}
TIME_KEYS = {
    "time",
    "showtime",
    "show_time",
    "starttime",
    "start_time",
    "performancetime",
    "performance_time",
}
URL_KEYS = {
    "ticketurl",
    "ticket_url",
    "purchaseurl",
    "purchase_url",
    "bookingurl",
    "booking_url",
    "seatmapurl",
    "seat_map_url",
    "seatpreviewurl",
    "seat_preview_url",
    "url",
    "href",
}
SEAT_URL_KEYS = {
    "seatmapurl",
    "seat_map_url",
    "data_seat_map_url",
    "seatpreviewurl",
    "seat_preview_url",
    "data_seat_preview_url",
    "seatingurl",
    "seating_url",
    "data_seating_url",
}
FORMAT_KEYS = {
    "format",
    "formatname",
    "format_name",
    "experience",
    "experiencename",
    "experience_name",
    "presentation",
}
AUDITORIUM_KEYS = {"auditorium", "auditoriumname", "auditorium_name", "screen", "screenname"}
ID_KEYS = {
    "id",
    "sessionid",
    "session_id",
    "showtimeid",
    "showtime_id",
    "performanceid",
    "performance_id",
    "scheduleid",
    "schedule_id",
}


@dataclass(frozen=True)
class LandmarkShowing:
    movie_title: str
    starts_at: datetime
    ticket_url: str
    source_id: str
    format: str | None = None
    auditorium: str | None = None
    seat_map_url: str | None = None


@dataclass(frozen=True)
class LandmarkCollectionSummary:
    discovered: int
    checked: int
    failed: int
    database_url: str
    status: str


async def discover_landmark_showings(
    url: str = LANDMARK_REGINA_URL, wait_ms: int = 5000
) -> list[LandmarkShowing]:
    payloads: list[Any] = []
    async with _playwright_page() as page:
        tasks: list[asyncio.Task[None]] = []

        async def inspect_response(response: Any) -> None:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                payloads.append(await response.json())
            except Exception:
                return

        page.on("response", lambda response: tasks.append(asyncio.create_task(inspect_response(response))))
        await _goto_with_fallback(page, url)
        await page.wait_for_timeout(wait_ms)
        await _raise_for_access_denied(page)
        if tasks:
            await asyncio.gather(*tasks)
        dom_candidates = await _read_dom_candidates(page)

    showings = extract_showings_from_payloads(payloads, url)
    if not showings:
        showings = extract_showings_from_dom_candidates(dom_candidates, url)
    return showings


def run_landmark_collection(
    database_url: str,
    showtimes_url: str = LANDMARK_REGINA_URL,
    wait_ms: int = 5000,
    max_showings: int | None = None,
    probe_seats: bool = True,
) -> LandmarkCollectionSummary:
    try:
        showings = asyncio.run(discover_landmark_showings(showtimes_url, wait_ms=wait_ms))
    except RuntimeError as error:
        if "Akamai Access Denied" not in str(error):
            raise
        showings = discover_landmark_atom_showings()
    if max_showings is not None:
        showings = showings[:max_showings]

    repository = repository_from_url(database_url)
    repository.init_schema()
    return write_landmark_showings(
        repository,
        showings,
        database_url=database_url,
        probe_seats=probe_seats,
    )


def write_landmark_showings(
    repository: Repository,
    showings: list[LandmarkShowing],
    database_url: str,
    probe_seats: bool = True,
) -> LandmarkCollectionSummary:
    run_id = repository.start_run(ScrapeRun(chain="Landmark"))
    checked = 0
    failed = 0

    try:
        repository.upsert_theater(LANDMARK_REGINA_THEATER)
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
                        theater_external_id=LANDMARK_REGINA_EXTERNAL_ID,
                        movie_normalized_title=normalize_movie_title(showing.movie_title),
                        starts_at=showing.starts_at,
                        format=showing.format,
                        auditorium=showing.auditorium,
                        ticket_url=showing.ticket_url,
                        source_id=showing.source_id,
                    )
                )
                parsed = _unknown_result("Seat probe skipped")
                if probe_seats:
                    parsed = _probe_showing_seats(showing)
                repository.insert_snapshot(_snapshot_from_result(showing, parsed))
            except Exception as error:
                failed += 1
                _insert_failed_snapshot(repository, showing, error)

        status = _run_status(checked, failed)
        repository.finish_run(run_id, status, count_checked=checked, count_failed=failed)
        return LandmarkCollectionSummary(
            discovered=len(showings),
            checked=checked,
            failed=failed,
            database_url=database_url,
            status=status,
        )
    except Exception:
        repository.finish_run(run_id, "failed", count_checked=checked, count_failed=max(failed, 1))
        raise


def extract_showings_from_payloads(
    payloads: list[Any], base_url: str, now: datetime | None = None
) -> list[LandmarkShowing]:
    discovered: list[LandmarkShowing] = []
    for payload in payloads:
        discovered.extend(_walk_payload(payload, base_url, {}, now or datetime.now(REGINA_TZ)))
    return _dedupe_showings(discovered)


def extract_showings_from_dom_candidates(
    candidates: list[dict[str, Any]], base_url: str, now: datetime | None = None
) -> list[LandmarkShowing]:
    discovered: list[LandmarkShowing] = []
    current = now or datetime.now(REGINA_TZ)
    for candidate in candidates:
        attrs = candidate.get("attrs") or {}
        href = candidate.get("href") or attrs.get("href") or attrs.get("data-url")
        nearby_text = str(candidate.get("nearbyText") or "")
        text = " ".join(
            str(part)
            for part in (
                candidate.get("text"),
                attrs.get("aria-label"),
                attrs.get("title"),
                nearby_text,
            )
            if part
        )
        starts_at = _parse_first_datetime_from_text(text, current)
        movie_title = _best_dom_title(nearby_text or text, starts_at)
        if not href or not starts_at or not movie_title:
            continue
        ticket_url = urljoin(base_url, str(href))
        seat_map_url = _first_url_from_attrs(attrs, base_url, SEAT_URL_KEYS)
        discovered.append(
            LandmarkShowing(
                movie_title=movie_title,
                starts_at=starts_at,
                ticket_url=ticket_url,
                seat_map_url=seat_map_url,
                source_id=_source_id(None, movie_title, starts_at, ticket_url),
                format=_format_from_text(text),
            )
        )
    return _dedupe_showings(discovered)


def discover_landmark_atom_showings() -> list[LandmarkShowing]:
    return [landmark_showing_from_atom(showing) for showing in discover_atom_showings()]


def normalize_movie_title(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug or "untitled"


def summary_to_json(summary: LandmarkCollectionSummary) -> str:
    return json.dumps(asdict(summary), indent=2)


def showings_to_json(showings: list[LandmarkShowing]) -> str:
    return json.dumps([_showing_to_dict(showing) for showing in showings], indent=2)


def _playwright_page():
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run `pip install -e '.[collector]'` "
            "and then `playwright install chromium` before collecting live sites."
        ) from error

    class PageContext:
        async def __aenter__(self):
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch()
            self.context = await self.browser.new_context(
                user_agent=LANDMARK_USER_AGENT,
                locale="en-CA",
                timezone_id="America/Regina",
                viewport={"width": 1365, "height": 900},
            )
            self.page = await self.context.new_page()
            return self.page

        async def __aexit__(self, exc_type, exc, traceback):
            await self.context.close()
            await self.browser.close()
            await self.playwright.stop()

    return PageContext()


async def _goto_with_fallback(page: Any, url: str) -> None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
    except Exception:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)


async def _read_dom_candidates(page: Any) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href], button, [data-seat-map-url], [data-session-id]'))
          .map((node) => {
            const attrs = {};
            for (const attr of node.attributes || []) attrs[attr.name] = attr.value;
            const container = node.closest('article, li, section, .movie, .showtime, .showtimes, [data-movie-id], [data-session-id]');
            return {
              tag: node.tagName.toLowerCase(),
              href: node.href || attrs.href || null,
              text: (node.innerText || node.textContent || '').trim(),
              nearbyText: container ? (container.innerText || container.textContent || '').trim() : '',
              attrs
            };
          })
        """
    )


async def _raise_for_access_denied(page: Any) -> None:
    title = await page.title()
    try:
        body = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    if _is_access_denied(title, body):
        raise RuntimeError(
            "Landmark returned Akamai Access Denied to the Playwright browser. "
            "No Landmark login is required, but this live scrape is currently "
            "blocked by edge bot protection."
        )


def _is_access_denied(title: str, body: str) -> bool:
    text = f"{title}\n{body}".lower()
    return "access denied" in text and (
        "errors.edgesuite.net" in text or "permission to access" in text
    )


def _walk_payload(
    value: Any,
    base_url: str,
    context: dict[str, str],
    now: datetime,
) -> list[LandmarkShowing]:
    discovered: list[LandmarkShowing] = []
    if isinstance(value, dict):
        current_context = dict(context)
        title = _movie_title_from_dict(value, broad=False)
        if title:
            current_context["movie_title"] = title
        date_value = _first_text(value, DATE_KEYS)
        if date_value:
            current_context["date"] = date_value

        starts_at = _starts_at_from_dict(value, now, current_context.get("date"))
        movie_title = _movie_title_from_dict(value, broad=True) or current_context.get("movie_title")
        ticket_url = _url_from_dict(value, base_url, URL_KEYS)
        if starts_at and movie_title and ticket_url:
            seat_map_url = _url_from_dict(value, base_url, SEAT_URL_KEYS)
            discovered.append(
                LandmarkShowing(
                    movie_title=movie_title,
                    starts_at=starts_at,
                    ticket_url=ticket_url,
                    source_id=_source_id(_first_text(value, ID_KEYS), movie_title, starts_at, ticket_url),
                    format=_first_text(value, FORMAT_KEYS),
                    auditorium=_first_text(value, AUDITORIUM_KEYS),
                    seat_map_url=seat_map_url,
                )
            )

        for child in value.values():
            discovered.extend(_walk_payload(child, base_url, current_context, now))
    elif isinstance(value, list):
        for child in value:
            discovered.extend(_walk_payload(child, base_url, context, now))
    return discovered


def _movie_title_from_dict(value: dict[str, Any], broad: bool) -> str | None:
    title = _first_text(value, MOVIE_TITLE_KEYS)
    if title:
        return title
    if broad and _looks_like_showing(value):
        return _first_text(value, FALLBACK_TITLE_KEYS)
    if not broad and _contains_showing_child(value):
        return _first_text(value, FALLBACK_TITLE_KEYS)
    return None


def _starts_at_from_dict(
    value: dict[str, Any], now: datetime, context_date: str | None = None
) -> datetime | None:
    for key, raw in value.items():
        if _norm_key(key) in START_KEYS:
            parsed = _parse_datetime(raw, now=now)
            if parsed:
                return parsed
            if context_date:
                parsed = _parse_datetime(f"{context_date} {raw}", now=now)
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
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if isinstance(raw, date):
        return _as_utc(datetime.combine(raw, time.min, REGINA_TZ))
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 10_000_000_000:
            value = value / 1000
        if value > 1_000_000_000:
            return datetime.fromtimestamp(value, UTC)

    text = str(raw).strip()
    if not text:
        return None
    dotnet = re.search(r"/Date\((\d+)", text)
    if dotnet:
        return datetime.fromtimestamp(int(dotnet.group(1)) / 1000, UTC)

    iso_text = text.replace("Z", "+00:00")
    try:
        return _as_utc(datetime.fromisoformat(iso_text))
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%A, %B %d, %Y %I:%M %p",
        "%a, %b %d, %Y %I:%M %p",
    )
    for fmt in formats:
        try:
            return _as_utc(datetime.strptime(text, fmt).replace(tzinfo=REGINA_TZ))
        except ValueError:
            continue

    no_year_match = re.search(
        r"(?P<month>[A-Za-z]{3,9})\s+(?P<day>\d{1,2}).*?(?P<clock>\d{1,2}:\d{2}\s*[AP]M)",
        text,
        re.IGNORECASE,
    )
    if no_year_match:
        with_year = (
            f"{no_year_match.group('month')} {no_year_match.group('day')}, "
            f"{now.year} {no_year_match.group('clock')}"
        )
        return _parse_datetime(with_year, now=now)

    return None


def _parse_first_datetime_from_text(text: str, now: datetime) -> datetime | None:
    date_time = re.search(
        r"([A-Za-z]{3,9}\s+\d{1,2}(?:,\s*\d{4})?).{0,80}?(\d{1,2}:\d{2}\s*[AP]M)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if date_time:
        value = date_time.group(0)
        if not re.search(r"\d{4}", value):
            value = re.sub(r"([A-Za-z]{3,9}\s+\d{1,2})", rf"\1, {now.year}", value, count=1)
        return _parse_datetime(value, now=now)

    time_only = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", text, re.IGNORECASE)
    if time_only:
        local = datetime.combine(now.date(), datetime.strptime(time_only.group(1).upper(), "%I:%M %p").time(), REGINA_TZ)
        return _as_utc(local)
    return None


def _best_dom_title(text: str, starts_at: datetime | None) -> str | None:
    del starts_at
    lines = [line.strip() for line in re.split(r"[\n|]+", text) if line.strip()]
    for line in lines:
        if _line_looks_like_title(line):
            return line
    return None


def _line_looks_like_title(line: str) -> bool:
    lowered = line.lower()
    if len(line) < 2 or len(line) > 80:
        return False
    blocked_terms = {"ticket", "seat", "available", "unavailable", "showtime", "book", "buy"}
    if any(term in lowered for term in blocked_terms):
        return False
    if lowered in {"laser ultra", "premiere", "real d 3d", "3d", "imax"}:
        return False
    if re.search(r"\d{1,2}:\d{2}\s*[ap]m", lowered):
        return False
    if re.search(r"\b(mon|tue|wed|thu|fri|sat|sun|january|february|march|april|may|june|july|august|september|october|november|december)\b", lowered):
        return False
    return bool(re.search(r"[A-Za-z]", line))


def _format_from_text(text: str) -> str | None:
    for known in ("Laser Ultra", "Premiere", "Real D 3D", "3D", "IMAX"):
        if known.lower() in text.lower():
            return known
    return None


def _url_from_dict(value: dict[str, Any], base_url: str, keys: set[str]) -> str | None:
    raw = _first_text(value, keys)
    if not raw:
        return None
    return urljoin(base_url, raw)


def _first_url_from_attrs(attrs: dict[str, Any], base_url: str, keys: set[str]) -> str | None:
    raw = _first_text(attrs, keys)
    return urljoin(base_url, raw) if raw else None


def _first_text(value: dict[str, Any], keys: set[str]) -> str | None:
    raw = _first_raw(value, keys)
    if raw is None:
        return None
    if isinstance(raw, (str, int, float)):
        text = str(raw).strip()
        return text or None
    return None


def _first_raw(value: dict[str, Any], keys: set[str]) -> Any | None:
    for key, raw in value.items():
        if _norm_key(key) in keys and raw not in (None, ""):
            return raw
    return None


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", key.replace("-", "_").lower())


def _looks_like_showing(value: dict[str, Any]) -> bool:
    keys = {_norm_key(key) for key in value}
    return bool(keys & (START_KEYS | TIME_KEYS)) and bool(keys & URL_KEYS)


def _contains_showing_child(value: dict[str, Any]) -> bool:
    for child in value.values():
        if isinstance(child, dict) and _looks_like_showing(child):
            return True
        if isinstance(child, list) and any(isinstance(item, dict) and _looks_like_showing(item) for item in child):
            return True
    return False


def _source_id(
    raw_id: str | None,
    movie_title: str,
    starts_at: datetime,
    ticket_url: str,
) -> str:
    if raw_id:
        return f"landmark-regina-{raw_id}"
    digest = hashlib.sha1(ticket_url.encode("utf-8")).hexdigest()[:8]
    return f"landmark-regina-{normalize_movie_title(movie_title)}-{starts_at:%Y%m%d%H%M}-{digest}"


def _dedupe_showings(showings: list[LandmarkShowing]) -> list[LandmarkShowing]:
    deduped: dict[str, LandmarkShowing] = {}
    for showing in showings:
        deduped.setdefault(showing.source_id, showing)
    return sorted(deduped.values(), key=lambda item: (item.starts_at, item.movie_title))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=REGINA_TZ)
    return value.astimezone(UTC)


def _snapshot_from_result(showing: LandmarkShowing, parsed: SeatParseResult) -> SeatSnapshot:
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
    repository: Repository, showing: LandmarkShowing, error: Exception
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


def _probe_showing_seats(showing: LandmarkShowing) -> SeatParseResult:
    url = showing.seat_map_url or showing.ticket_url
    if "atomtickets.com/checkout/" in url:
        return probe_atom_checkout_seat_map(url)
    return asyncio.run(probe_seat_map(url))


def landmark_showing_from_atom(showing: AtomShowing) -> LandmarkShowing:
    return LandmarkShowing(
        movie_title=showing.movie_title,
        starts_at=showing.starts_at,
        ticket_url=showing.ticket_url,
        source_id=showing.source_id,
        format=showing.format,
        auditorium=showing.auditorium,
        seat_map_url=showing.seat_map_url,
    )


def _unknown_result(message: str) -> SeatParseResult:
    return SeatParseResult(
        inferred_occupied=None,
        available_seats=None,
        total_sellable_seats=None,
        raw_status="unknown",
        confidence="low",
        error_message=message,
    )


def _run_status(checked: int, failed: int) -> str:
    if checked == 0:
        return "failed"
    if failed == 0:
        return "success"
    if failed < checked:
        return "partial"
    return "failed"


def _showing_to_dict(showing: LandmarkShowing) -> dict[str, Any]:
    data = asdict(showing)
    data["starts_at"] = showing.starts_at.isoformat()
    return data
