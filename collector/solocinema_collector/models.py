from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, HttpUrl, field_validator


SeatStatus = Literal["available", "unknown", "failed", "unavailable"]
Confidence = Literal["high", "medium", "low"]
Chain = Literal["Landmark", "Cineplex", "Other"]


class Theater(BaseModel):
    chain: Chain
    name: str
    city: str = "Regina"
    external_id: str
    ticketing_url: HttpUrl | str


class Movie(BaseModel):
    normalized_title: str
    source_title: str
    poster_url: HttpUrl | str | None = None
    rating: str | None = None
    runtime_minutes: int | None = None


class Showing(BaseModel):
    theater_external_id: str
    movie_normalized_title: str
    starts_at: datetime
    ticket_url: HttpUrl | str
    source_id: str
    format: str | None = None
    auditorium: str | None = None

    @field_validator("ticket_url")
    @classmethod
    def _ticket_url_must_be_http(cls, value: HttpUrl | str) -> HttpUrl | str:
        if urlsplit(str(value)).scheme not in ("http", "https"):
            raise ValueError("ticket_url must be an http(s) URL")
        return value


class SeatSnapshot(BaseModel):
    showing_source_id: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    inferred_occupied: int | None
    available_seats: int | None
    total_sellable_seats: int | None
    raw_status: SeatStatus
    confidence: Confidence
    error_message: str | None = None


class SeatParseResult(BaseModel):
    inferred_occupied: int | None
    available_seats: int | None
    total_sellable_seats: int | None
    raw_status: SeatStatus
    confidence: Confidence
    unknown_seats: int = 0
    blocked_seats: int = 0
    error_message: str | None = None


class ScrapeRun(BaseModel):
    chain: Chain
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    status: Literal["running", "success", "partial", "failed"] = "running"
    count_checked: int = 0
    count_failed: int = 0
