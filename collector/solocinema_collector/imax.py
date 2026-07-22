"""Kramer IMAX (Saskatchewan Science Centre) collector.

The Science Centre sells IMAX tickets through Vantix ATMS at
tickets.sasksciencecentre.com. Discovery and seat data are all plain
unauthenticated GETs (see docs/imax-research.md):

- ``default.aspx?tagid=18`` lists every Kramer IMAX item (movie).
- ``/atms/uc/services/Calendar.aspx?item=<id>&v=All`` returns every showtime
  for an item in one fragment, each with a live "N Remaining" count.
- Reserved-seating showings additionally expose a per-seat SVG at
  seats-api.ticketclick.com keyed by an org API key embedded in the public
  Selection.aspx page. Seats carry a bare ``locked`` attribute when taken.

General-admission showings (the IMAX documentaries) have no seat map; for
those we infer occupancy from the calendar's remaining count against the
auditorium's known capacity, at reduced confidence.
"""

from __future__ import annotations

import html as html_module
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .landmark import normalize_movie_title
from .models import Movie, ScrapeRun, SeatParseResult, SeatSnapshot, Showing, Theater
from .storage import Repository, repository_from_url
from .url_guard import require_allowed_url


IMAX_TICKETS_BASE = "https://tickets.sasksciencecentre.com"
IMAX_SEATS_API_BASE = "https://seats-api.ticketclick.com"
KRAMER_TAG_ID = "18"
# Public org key embedded in every Selection.aspx page; refreshed at collect
# time via discover_seats_api_key, this is only the last known value.
IMAX_SEATS_API_KEY = os.environ.get("IMAX_SEATS_API_KEY")
DEFAULT_SEATS_API_KEY = "key-ssc-8001482daac3efd0464d67b3"
# The theatre is a single 154-seat auditorium ("Main", incl. wheelchair
# stalls). Used to infer occupancy for general-admission showings where only
# a remaining count is published.
KRAMER_AUDITORIUM_CAPACITY = 154
IMAX_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REGINA_TZ = ZoneInfo("America/Regina")

KRAMER_THEATER = Theater(
    chain="Other",
    name="Kramer IMAX Theatre",
    city="Regina",
    external_id="kramer-imax",
    ticketing_url=f"{IMAX_TICKETS_BASE}/default.aspx?tagid={KRAMER_TAG_ID}",
)

# Item cards render as an <h2> title followed by a link that is either
# DateSelection.aspx?item=N (several showtimes) or Selection.aspx?item=N&sch=M
# (a single remaining showtime).
_TITLE_OR_LINK = re.compile(
    r'<h2[^>]*>\s*(?P<title>[^<]+?)\s*</h2>'
    r'|href="(?P<link>/(?:Date)?Selection\.aspx\?item=\d+[^"]*)"'
)
_EVENT_LISTING = re.compile(
    r'<div class="EventListing[^"]*">(?P<block>.*?)</div>\s*</div>', re.S
)
_SCHEDULE_LINK = re.compile(
    r'data-schedule="(?P<sch>\d+)"[^>]*data-scheduleDate="(?P<when>[^"]+)"'
)
_REMAINING = re.compile(r"\b(\d+)\s+Remaining\b")
_SEAT_CIRCLE = re.compile(r"<circle\s[^>]*?seat-id=[^>]*?/>")
# `locked` is a bare (valueless) attribute; quoted attribute values are
# stripped before matching so the word can't false-positive inside the
# free-text message="..." popover attributes.
_QUOTED_VALUE = re.compile(r'"[^"]*"')
_LOCKED = re.compile(r"\slocked(?=[\s/>])")
_API_KEY = re.compile(r'apiKey:\s*"(key-[^"]+)"')
# data-scheduleDate="Sunday July 19, 2026 - 11:00 AM"; commas are stripped
# before parsing since the <p> text variant writes "Sunday, July 19, 2026".
_SCHEDULE_DATE_FORMAT = "%A %B %d %Y - %I:%M %p"


@dataclass(frozen=True)
class ImaxItem:
    item_id: str
    title: str


@dataclass(frozen=True)
class ImaxShowing:
    movie_title: str
    starts_at: datetime
    ticket_url: str
    source_id: str
    schedule_id: str
    item_id: str
    remaining: int | None = None


@dataclass(frozen=True)
class ImaxCollectionSummary:
    discovered: int
    checked: int
    failed: int
    database_url: str
    status: str


def discover_imax_showings(tag_id: str = KRAMER_TAG_ID) -> list[ImaxShowing]:
    listing = _open_text(f"{IMAX_TICKETS_BASE}/default.aspx?tagid={tag_id}")
    showings: list[ImaxShowing] = []
    for item in parse_imax_items(listing):
        calendar = _open_text(
            f"{IMAX_TICKETS_BASE}/atms/uc/services/Calendar.aspx?item={item.item_id}&v=All"
        )
        showings.extend(parse_imax_calendar(calendar, item))
    deduped: dict[str, ImaxShowing] = {}
    for showing in showings:
        deduped.setdefault(showing.source_id, showing)
    return sorted(deduped.values(), key=lambda item: (item.starts_at, item.movie_title))


def parse_imax_items(html: str) -> list[ImaxItem]:
    items: list[ImaxItem] = []
    pending_title: str | None = None
    for match in _TITLE_OR_LINK.finditer(html):
        title = match.group("title")
        if title is not None:
            text = _unescape(title)
            # The shopping-cart panel renders an <h2>Your Order</h2> before
            # the item cards.
            pending_title = None if text.lower() == "your order" else text
            continue
        link = match.group("link")
        if pending_title and link:
            item_id = re.search(r"item=(\d+)", link)
            if item_id:
                items.append(ImaxItem(item_id=item_id.group(1), title=pending_title))
            pending_title = None
    deduped: dict[str, ImaxItem] = {}
    for item in items:
        deduped.setdefault(item.item_id, item)
    return list(deduped.values())


def parse_imax_calendar(html: str, item: ImaxItem) -> list[ImaxShowing]:
    showings: list[ImaxShowing] = []
    for block_match in _EVENT_LISTING.finditer(html):
        block = block_match.group("block")
        link = _SCHEDULE_LINK.search(block)
        if not link:
            continue
        starts_at = _parse_schedule_date(link.group("when"))
        if not starts_at:
            continue
        remaining_match = _REMAINING.search(block)
        schedule_id = link.group("sch")
        showings.append(
            ImaxShowing(
                movie_title=item.title,
                starts_at=starts_at,
                ticket_url=f"{IMAX_TICKETS_BASE}/Selection.aspx?sch={schedule_id}",
                source_id=f"kramer-imax-atms-{schedule_id}",
                schedule_id=schedule_id,
                item_id=item.item_id,
                remaining=int(remaining_match.group(1)) if remaining_match else None,
            )
        )
    return showings


def discover_seats_api_key(schedule_id: str) -> str | None:
    """Scrape the seats API key from a public Selection.aspx page."""
    try:
        html = _open_text(f"{IMAX_TICKETS_BASE}/Selection.aspx?sch={schedule_id}")
    except Exception:
        return None
    match = _API_KEY.search(html)
    return match.group(1) if match else None


def probe_imax_seat_map(
    schedule_id: str, api_key: str | None = None
) -> SeatParseResult | None:
    """Count seats from the reserved-seating SVG; None when the showing is
    general admission (the seats API has no chart for it)."""
    key = api_key or IMAX_SEATS_API_KEY or DEFAULT_SEATS_API_KEY
    url = (
        f"{IMAX_SEATS_API_BASE}/api/seatingcharts/svg/organization/"
        f"{key}/atmsSchedule/{schedule_id}"
    )
    try:
        svg = _open_text(url)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    return parse_imax_seat_svg(svg)


def parse_imax_seat_svg(svg: str) -> SeatParseResult:
    circles = _SEAT_CIRCLE.findall(svg)
    if not circles:
        return SeatParseResult(
            inferred_occupied=None,
            available_seats=None,
            total_sellable_seats=None,
            raw_status="unknown",
            confidence="low",
            error_message="No seats found in IMAX seat map SVG",
        )
    locked = sum(
        1 for circle in circles if _LOCKED.search(_QUOTED_VALUE.sub('""', circle))
    )
    return SeatParseResult(
        inferred_occupied=locked,
        available_seats=len(circles) - locked,
        total_sellable_seats=len(circles),
        raw_status="available",
        # "locked" folds sold, held and house-blocked seats together, so this
        # can never be distinguished from official sales data.
        confidence="medium",
        blocked_seats=0,
    )


def result_from_remaining(remaining: int | None) -> SeatParseResult:
    """Occupancy inferred from the calendar's remaining count alone (used for
    general-admission showings and showings outside the seat-probe window)."""
    if remaining is None:
        return _unknown_result("IMAX calendar listed no remaining count")
    occupied = max(0, KRAMER_AUDITORIUM_CAPACITY - remaining)
    return SeatParseResult(
        inferred_occupied=occupied,
        available_seats=remaining,
        total_sellable_seats=KRAMER_AUDITORIUM_CAPACITY,
        raw_status="available",
        # The venue may hold seats back from online sale, so remaining-based
        # occupancy can overcount; the seat-map probe is preferred.
        confidence="low",
    )


def run_imax_collection(
    database_url: str,
    max_showings: int | None = None,
    probe_seats: bool = True,
    probe_days: int = 3,
) -> ImaxCollectionSummary:
    showings = discover_imax_showings()
    if max_showings is not None:
        showings = showings[:max_showings]

    repository = repository_from_url(database_url)
    repository.init_schema()
    return write_imax_showings(
        repository,
        showings,
        database_url=database_url,
        probe_seats=probe_seats,
        probe_days=probe_days,
    )


def write_imax_showings(
    repository: Repository,
    showings: list[ImaxShowing],
    database_url: str,
    probe_seats: bool = True,
    probe_days: int = 3,
    now: datetime | None = None,
) -> ImaxCollectionSummary:
    run_id = repository.start_run(ScrapeRun(chain="Other"))
    checked = 0
    failed = 0
    api_key: str | None = None
    now = now or datetime.now(UTC)

    try:
        repository.upsert_theater(KRAMER_THEATER)
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
                        theater_external_id=KRAMER_THEATER.external_id,
                        movie_normalized_title=normalize_movie_title(showing.movie_title),
                        starts_at=showing.starts_at,
                        format="IMAX",
                        ticket_url=showing.ticket_url,
                        source_id=showing.source_id,
                    )
                )
                # Out-of-window showings get no snapshot row; the screenings
                # view reads missing snapshots as status "unknown". Without
                # probing (validation mode) every showing keeps its
                # calendar-derived remaining-seats snapshot.
                parsed = None
                if probe_seats and _within_probe_window(showing, now, probe_days):
                    if api_key is None:
                        api_key = (
                            IMAX_SEATS_API_KEY
                            or discover_seats_api_key(showing.schedule_id)
                            or DEFAULT_SEATS_API_KEY
                        )
                    parsed = probe_imax_seat_map(showing.schedule_id, api_key)
                    if parsed is None:
                        parsed = result_from_remaining(showing.remaining)
                elif not probe_seats:
                    parsed = result_from_remaining(showing.remaining)
                if parsed is not None:
                    repository.insert_snapshot(_snapshot_from_result(showing, parsed))
            except Exception as error:
                failed += 1
                _insert_failed_snapshot(repository, showing, error)

        status = _run_status(checked, failed)
        repository.finish_run(run_id, status, count_checked=checked, count_failed=failed)
        return ImaxCollectionSummary(
            discovered=len(showings),
            checked=checked,
            failed=failed,
            database_url=database_url,
            status=status,
        )
    except Exception:
        repository.finish_run(run_id, "failed", count_checked=checked, count_failed=max(failed, 1))
        raise


def summary_to_json(summary: ImaxCollectionSummary) -> str:
    return json.dumps(asdict(summary), indent=2)


def showings_to_json(showings: list[ImaxShowing]) -> str:
    return json.dumps([_showing_to_dict(showing) for showing in showings], indent=2)


def _within_probe_window(showing: ImaxShowing, now: datetime, probe_days: int) -> bool:
    delta = showing.starts_at - now
    return delta.total_seconds() >= -3 * 3600 and delta.days < probe_days


def _parse_schedule_date(raw: str) -> datetime | None:
    text = re.sub(r"\s+", " ", raw.replace(",", " ")).strip()
    try:
        local = datetime.strptime(text, _SCHEDULE_DATE_FORMAT).replace(tzinfo=REGINA_TZ)
    except ValueError:
        return None
    return local.astimezone(UTC)


def _snapshot_from_result(showing: ImaxShowing, parsed: SeatParseResult) -> SeatSnapshot:
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
    repository: Repository, showing: ImaxShowing, error: Exception
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


def _run_status(checked: int, failed: int) -> str:
    if checked == 0:
        return "failed"
    if failed == 0:
        return "success"
    if failed < checked:
        return "partial"
    return "failed"


def _open_text(url: str) -> str:
    require_allowed_url(url)
    request = Request(url, headers={"User-Agent": IMAX_USER_AGENT})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _unescape(text: str) -> str:
    return html_module.unescape(text).strip()


def _showing_to_dict(showing: ImaxShowing) -> dict[str, Any]:
    data = asdict(showing)
    data["starts_at"] = showing.starts_at.isoformat()
    return data
