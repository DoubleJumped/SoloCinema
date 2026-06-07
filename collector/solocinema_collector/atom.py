from __future__ import annotations

import html
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from .models import SeatParseResult
from .seat_parser import parse_atom_seat_map_fragments


ATOM_LANDMARK_REGINA_URL = "https://www.atomtickets.com/theaters/landmark-cinemas-regina/49885"
ATOM_CINEPLEX_SOUTHLAND_URL = (
    "https://www.atomtickets.com/theaters/cineplex-odeon-southland-mall-cinemas/6446"
)
ATOM_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REGINA_TZ = ZoneInfo("America/Regina")


@dataclass(frozen=True)
class AtomShowing:
    movie_title: str
    starts_at: datetime
    ticket_url: str
    source_id: str
    format: str | None = None
    auditorium: str | None = None
    seat_map_url: str | None = None


def discover_atom_showings(
    url: str = ATOM_LANDMARK_REGINA_URL,
    source_prefix: str = "landmark-regina",
    include_unticketed: bool = False,
) -> list[AtomShowing]:
    text = _open_text(url)
    parser = AtomTheaterParser(
        url,
        source_prefix=source_prefix,
        include_unticketed=include_unticketed,
    )
    parser.feed(text)
    return parser.showings


def discover_cineplex_southland_atom_showings() -> list[AtomShowing]:
    return discover_atom_showings(
        ATOM_CINEPLEX_SOUTHLAND_URL,
        source_prefix="cineplex-southland",
        include_unticketed=True,
    )


def probe_atom_checkout_seat_map(checkout_url: str) -> SeatParseResult:
    opener = _opener()
    checkout_html = _open_text(checkout_url, opener=opener)
    context = _checkout_context(checkout_html)
    showtime_context = context.get("showtimeContext") or {}
    showtime_id = str(showtime_context.get("showtimeId") or _checkout_id(checkout_url))
    client_request_id = str(context.get("clientRequestId") or "")
    area_categories = showtime_context.get("areaCategories") or [None]

    fragments: list[str] = []
    for area_category in area_categories:
        params: dict[str, str] = {
            "numTickets": "1",
            "clientRequestId": client_request_id,
        }
        if area_category:
            params["areaCategory"] = str(area_category)
        if showtime_context.get("eventId"):
            params["eventId"] = str(showtime_context["eventId"])
        seat_map_url = urljoin(checkout_url, f"/checkout/{showtime_id}/seat-map?{urlencode(params)}")
        fragments.append(_open_text(seat_map_url, opener=opener))

    return parse_atom_seat_map_fragments(fragments)


def _opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def _open_text(url: str, opener: Any | None = None) -> str:
    request = Request(url, headers={"User-Agent": ATOM_USER_AGENT})
    response = (opener or _opener()).open(request, timeout=30)
    charset = response.headers.get_content_charset() or "utf-8"
    return response.read().decode(charset, errors="replace")


def _checkout_id(checkout_url: str) -> str:
    match = re.search(r"/checkout/(\d+)", checkout_url)
    if not match:
        raise ValueError(f"Atom checkout URL does not contain a showtime id: {checkout_url}")
    return match.group(1)


def _checkout_context(checkout_html: str) -> dict[str, Any]:
    match = re.search(r'data-context="([^"]+)"', checkout_html)
    if not match:
        raise ValueError("Atom checkout page did not include data-checkout-context")
    return json.loads(html.unescape(match.group(1)))


class AtomTheaterParser(HTMLParser):
    def __init__(
        self,
        base_url: str,
        source_prefix: str = "landmark-regina",
        include_unticketed: bool = False,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.source_prefix = source_prefix
        self.include_unticketed = include_unticketed
        self.selected_date: str | None = None
        self.current_title: str | None = None
        self.current_format: str | None = None
        self.capture_title = False
        self.pending_showtime: dict[str, str] | None = None
        self.showings: list[AtomShowing] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        self._read_selected_date(attributes)

        if tag == "li" and "data-showtime-entity-group" in attributes:
            self.current_title = None
            self.current_format = None

        if tag == "h2" and attributes.get("data-qa") == "ProductionHeader_Title":
            self.capture_title = True

        if tag == "div" and "format-showtimes" in _classes(attributes):
            self.current_format = _format_from_tags(attributes.get("data-showtime-tags"))

        if tag == "a" and "btn-showtime" in _classes(attributes):
            href = attributes.get("href", "")
            if href.startswith("/checkout/"):
                self.pending_showtime = {"href": href, "text": ""}
        if (
            tag == "button"
            and self.include_unticketed
            and "btn-showtime" in _classes(attributes)
        ):
            self.pending_showtime = {"href": "", "text": ""}

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self.capture_title:
            self.current_title = _collapse(text)
        if self.pending_showtime is not None:
            self.pending_showtime["text"] += f" {text}"

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.capture_title = False
        if tag in {"a", "button"} and self.pending_showtime is not None:
            self._append_pending_showtime()
            self.pending_showtime = None

    def _read_selected_date(self, attributes: dict[str, str]) -> None:
        raw = attributes.get("data-value")
        if not raw or self.selected_date:
            return
        try:
            value = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            return
        if value.get("isSelected") and value.get("serverFormat"):
            self.selected_date = str(value["serverFormat"])

    def _append_pending_showtime(self) -> None:
        if not self.current_title or not self.selected_date:
            return
        assert self.pending_showtime is not None
        starts_at = _parse_atom_datetime(self.selected_date, self.pending_showtime["text"])
        if not starts_at:
            return
        ticket_url = urljoin(self.base_url, self.pending_showtime["href"])
        showtime_id = _checkout_id(ticket_url) if self.pending_showtime["href"] else None
        self.showings.append(
            AtomShowing(
                movie_title=self.current_title,
                starts_at=starts_at,
                ticket_url=ticket_url,
                seat_map_url=ticket_url if showtime_id else None,
                source_id=_atom_source_id(
                    self.source_prefix,
                    showtime_id,
                    self.current_title,
                    starts_at,
                    ticket_url,
                ),
                format=self.current_format,
            )
        )


def _parse_atom_datetime(selected_date: str, time_text: str) -> datetime | None:
    match = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", time_text, re.IGNORECASE)
    if not match:
        return None
    local = datetime.strptime(f"{selected_date} {match.group(1).upper()}", "%Y-%m-%d %I:%M %p")
    return local.replace(tzinfo=REGINA_TZ).astimezone(UTC)


def _format_from_tags(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        tags = json.loads(html.unescape(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(tags, list):
        return None
    primary = [str(tag) for tag in tags if str(tag).lower() not in {"reserved seating", "recliner"}]
    return ", ".join(primary) if primary else None


def _atom_source_id(
    source_prefix: str,
    showtime_id: str | None,
    movie_title: str,
    starts_at: datetime,
    ticket_url: str,
) -> str:
    if showtime_id:
        return f"{source_prefix}-atom-{showtime_id}"
    source_key = f"{movie_title}|{starts_at.isoformat()}|{ticket_url}"
    digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:8]
    return f"{source_prefix}-atom-{_slug(movie_title)}-{starts_at:%Y%m%d%H%M}-{digest}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "untitled"


def _classes(attributes: dict[str, str]) -> set[str]:
    return {part.strip() for part in attributes.get("class", "").split() if part.strip()}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
