from __future__ import annotations

import json
import asyncio
from typing import Any

from .models import SeatParseResult
from .seat_parser import parse_dom_seats, parse_structured_seats


async def probe_seat_map(url: str, wait_ms: int = 5000) -> SeatParseResult:
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed. Run `pip install -e '.[collector]'` "
            "and then `playwright install chromium` before probing live sites."
        ) from error

    payload_results: list[SeatParseResult] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()

        tasks: list[asyncio.Task[None]] = []

        async def inspect_response(response: Any) -> None:
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                payload = await response.json()
            except Exception:
                return
            parsed = parse_structured_seats(payload)
            if parsed.total_sellable_seats:
                payload_results.append(parsed)

        page.on("response", lambda response: tasks.append(asyncio.create_task(inspect_response(response))))
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(wait_ms)
        if tasks:
            await asyncio.gather(*tasks)
        html = await page.content()
        await browser.close()

    if payload_results:
        return max(
            payload_results,
            key=lambda result: (
                result.total_sellable_seats or 0,
                result.available_seats or 0,
            ),
        )

    dom_result = parse_dom_seats(html)
    if dom_result.total_sellable_seats:
        return dom_result

    return SeatParseResult(
        inferred_occupied=None,
        available_seats=None,
        total_sellable_seats=None,
        raw_status="unknown",
        confidence="low",
        error_message="No parseable seat map found via network responses or DOM",
    )


def result_to_json(result: SeatParseResult) -> str:
    return json.dumps(result.model_dump(), indent=2)
