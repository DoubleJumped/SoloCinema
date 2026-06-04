from __future__ import annotations

from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any

from .models import SeatParseResult

AVAILABLE_TERMS = {
    "available",
    "open",
    "free",
    "selectable",
    "empty",
    "enabled",
}
OCCUPIED_TERMS = {
    "sold",
    "occupied",
    "booked",
    "taken",
    "reserved",
    "unavailable",
    "held",
    "hold",
    "selected",
}
BLOCKED_TERMS = {
    "blocked",
    "lock",
    "locked",
    "companion",
    "house",
    "maintenance",
}
ACCESSIBILITY_TERMS = {"accessible", "accessibility", "wheelchair", "ada"}
SEAT_KEYS = {
    "status",
    "state",
    "seatStatus",
    "seat_status",
    "availability",
    "available",
    "isAvailable",
    "isSold",
    "isBlocked",
    "type",
}


def parse_structured_seats(payload: Any) -> SeatParseResult:
    seats = list(_walk_seat_like_objects(payload))
    if not seats:
        return SeatParseResult(
            inferred_occupied=None,
            available_seats=None,
            total_sellable_seats=None,
            raw_status="unknown",
            confidence="low",
            error_message="No seat-like objects found in payload",
        )

    return _summarize_states(_classify_seat(seat) for seat in seats)


def parse_dom_seats(html: str) -> SeatParseResult:
    parser = SeatElementParser()
    parser.feed(html)
    if not parser.states:
        return SeatParseResult(
            inferred_occupied=None,
            available_seats=None,
            total_sellable_seats=None,
            raw_status="unknown",
            confidence="low",
            error_message="No seat elements found in DOM",
        )

    return _summarize_states(parser.states)


def _walk_seat_like_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        keys = set(value)
        has_state = bool(keys & SEAT_KEYS)
        has_identity = any(key in keys for key in ("row", "seat", "number", "label", "id"))
        if has_state and has_identity:
            yield value
        for child in value.values():
            yield from _walk_seat_like_objects(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_seat_like_objects(item)


def _classify_seat(seat: dict[str, Any]) -> str:
    tokens: set[str] = set()
    for key in SEAT_KEYS:
        if key not in seat:
            continue
        raw_value = seat[key]
        if isinstance(raw_value, bool):
            if key in {"available", "isAvailable"}:
                tokens.add("available" if raw_value else "unavailable")
            elif key == "isSold" and raw_value:
                tokens.add("sold")
            elif key == "isBlocked" and raw_value:
                tokens.add("blocked")
            continue
        tokens.update(_tokenize(raw_value))

    if tokens & BLOCKED_TERMS:
        return "blocked"
    if tokens & OCCUPIED_TERMS:
        return "occupied"
    if tokens & AVAILABLE_TERMS:
        return "available"
    if tokens & ACCESSIBILITY_TERMS:
        return "unknown"
    return "unknown"


def _tokenize(value: Any) -> set[str]:
    text = str(value).replace("_", " ").replace("-", " ").lower()
    return {part.strip() for part in text.split() if part.strip()}


def _summarize_states(states: Iterable[str]) -> SeatParseResult:
    counts = {"available": 0, "occupied": 0, "blocked": 0, "unknown": 0}
    for state in states:
        counts[state if state in counts else "unknown"] += 1

    total = sum(counts.values())
    if total == 0:
        return SeatParseResult(
            inferred_occupied=None,
            available_seats=None,
            total_sellable_seats=None,
            raw_status="unknown",
            confidence="low",
            error_message="No seat states could be classified",
        )

    inferred_occupied = counts["occupied"] + counts["blocked"]
    unknown_ratio = counts["unknown"] / total
    confidence = "high"
    if counts["blocked"] or unknown_ratio > 0:
        confidence = "medium"
    if unknown_ratio >= 0.15:
        confidence = "low"

    return SeatParseResult(
        inferred_occupied=inferred_occupied,
        available_seats=counts["available"],
        total_sellable_seats=total,
        raw_status="available",
        confidence=confidence,
        unknown_seats=counts["unknown"],
        blocked_seats=counts["blocked"],
    )


class SeatElementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.states: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        class_tokens = _tokenize(attributes.get("class", ""))
        data_state = (
            attributes.get("data-seat-state")
            or attributes.get("data-status")
            or attributes.get("aria-label")
            or attributes.get("title")
            or ""
        )
        all_tokens = class_tokens | _tokenize(data_state)
        interactive_or_shape = tag in {"button", "path", "rect", "circle", "g", "li"}
        explicit_seat = (
            "data-seat-state" in attributes
            or attributes.get("role") == "seat"
            or "seat" in data_state.lower()
        )
        is_seat = (interactive_or_shape and "seat" in class_tokens) or explicit_seat
        if not is_seat:
            return

        if all_tokens & BLOCKED_TERMS:
            self.states.append("blocked")
        elif all_tokens & OCCUPIED_TERMS:
            self.states.append("occupied")
        elif all_tokens & AVAILABLE_TERMS:
            self.states.append("available")
        else:
            self.states.append("unknown")
