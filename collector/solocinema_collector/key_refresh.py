"""Detect and recover from Cineplex rotating its public API key.

Cineplex ships its Azure APIM subscription key inside the public web-client
JS bundles. When they rotate it, our stored key starts returning 401s. This
module re-derives the current key the same way a browser gets it: fetch the
homepage, follow the Next.js chunk script tags, and scan the bundles for the
key. A candidate key is only ever adopted after it passes a live probe
against the showtimes endpoint.

If ``RENDER_API_KEY`` is set, a rotated key is also written back to this
service's Render env var (service id from ``RENDER_SERVICE_ID``, which
Render injects automatically) so future cron runs start with the fresh key.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .url_guard import require_allowed_url


CINEPLEX_HOME_URL = "https://www.cineplex.com/"
# Any cheap authenticated endpoint works as a probe; Southland showtimes is
# the same call the collector makes first anyway.
KEY_PROBE_URL = (
    "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes"
    "?language=en&locationId=4108"
)
RENDER_API_BASE = "https://api.render.com/v1"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_CHUNK_URL_RE = re.compile(
    r'src="(https://www\.cineplex\.com/next-static-files/_next/static/chunks/[^"]+\.js)"'
)
# The key appears both in runtime config objects and inline request headers.
_KEY_PATTERNS = (
    re.compile(r'ocpApimSubscriptionKey\s*:\s*"([0-9a-f]{32})"'),
    re.compile(r'"Ocp-Apim-Subscription-Key"\s*:\s*"([0-9a-f]{32})"'),
)

Fetcher = Callable[[str], str]


@dataclass
class KeyRefreshResult:
    current_key_valid: bool
    site_key: str | None
    site_key_valid: bool | None
    rotated: bool
    render_updated: bool
    active_key: str | None
    message: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _fetch_text(url: str) -> str:
    require_allowed_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_subscription_keys(text: str) -> Counter[str]:
    """Count every APIM-key-shaped literal in a JS bundle or HTML page."""
    counts: Counter[str] = Counter()
    for pattern in _KEY_PATTERNS:
        counts.update(pattern.findall(text))
    return counts


def fetch_site_key(fetch: Fetcher = _fetch_text) -> str | None:
    """Return the subscription key the Cineplex web client currently ships.

    The bundles reference more than one key (e.g. a separate one for the
    smart-app-banner endpoint); the theatrical-API key dominates by
    occurrence count, so the most common key wins.
    """
    home = fetch(CINEPLEX_HOME_URL)
    counts = extract_subscription_keys(home)
    for chunk_url in dict.fromkeys(_CHUNK_URL_RE.findall(home)):
        try:
            counts.update(extract_subscription_keys(fetch(chunk_url)))
        except (OSError, ValueError):
            continue  # a missing chunk must not sink the whole scan
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def validate_key(key: str, probe_url: str = KEY_PROBE_URL) -> bool:
    """True when the key is accepted by the live showtimes endpoint."""
    require_allowed_url(probe_url)
    request = Request(
        probe_url,
        headers={
            "Accept": "application/json",
            "Ocp-Apim-Subscription-Key": key,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return 200 <= response.status < 300
    except HTTPError as error:
        if error.code in (401, 403):
            return False
        raise


def update_render_env_var(
    key: str,
    api_key: str | None = None,
    service_id: str | None = None,
) -> bool:
    """PUT the new key to this service's Render env var. Returns True on success."""
    api_key = api_key or os.environ.get("RENDER_API_KEY")
    service_id = service_id or os.environ.get("RENDER_SERVICE_ID")
    if not api_key or not service_id:
        return False
    request = Request(
        f"{RENDER_API_BASE}/services/{service_id}/env-vars/CINEPLEX_SUBSCRIPTION_KEY",
        data=json.dumps({"value": key}).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return 200 <= response.status < 300


def refresh_cineplex_key(
    current_key: str | None,
    dry_run: bool = False,
    force: bool = False,
    fetch: Fetcher = _fetch_text,
    validate: Callable[[str], bool] = validate_key,
    update_render: Callable[[str], bool] = update_render_env_var,
) -> KeyRefreshResult:
    """Check the stored key and, if it is dead, adopt the site's current one.

    Never adopts a key that fails live validation, and only touches the
    Render env var for a validated, genuinely different key.
    """
    current_key_valid = bool(current_key) and validate(current_key)
    if current_key_valid and not force:
        return KeyRefreshResult(
            current_key_valid=True,
            site_key=None,
            site_key_valid=None,
            rotated=False,
            render_updated=False,
            active_key=current_key,
            message="Current key is valid; nothing to do.",
        )

    site_key = fetch_site_key(fetch)
    if site_key is None:
        return KeyRefreshResult(
            current_key_valid=current_key_valid,
            site_key=None,
            site_key_valid=None,
            rotated=False,
            render_updated=False,
            active_key=current_key if current_key_valid else None,
            message="No subscription key found in Cineplex site bundles.",
        )

    if site_key == current_key and not current_key_valid:
        return KeyRefreshResult(
            current_key_valid=False,
            site_key=site_key,
            site_key_valid=False,
            rotated=False,
            render_updated=False,
            active_key=None,
            message="Site still ships our (rejected) key; likely an outage, not a rotation.",
        )

    site_key_valid = validate(site_key)
    if not site_key_valid:
        return KeyRefreshResult(
            current_key_valid=current_key_valid,
            site_key=site_key,
            site_key_valid=False,
            rotated=False,
            render_updated=False,
            active_key=current_key if current_key_valid else None,
            message="Extracted site key failed validation; keeping current key.",
        )

    if dry_run:
        return KeyRefreshResult(
            current_key_valid=current_key_valid,
            site_key=site_key,
            site_key_valid=True,
            rotated=False,
            render_updated=False,
            active_key=current_key if current_key_valid else site_key,
            message="Dry run: valid site key found but nothing was updated.",
        )

    render_updated = site_key != current_key and update_render(site_key)
    return KeyRefreshResult(
        current_key_valid=current_key_valid,
        site_key=site_key,
        site_key_valid=True,
        rotated=site_key != current_key,
        render_updated=render_updated,
        active_key=site_key,
        message=(
            "Rotated to fresh site key"
            + (" and updated Render env var." if render_updated else
               "; Render env var not updated (set RENDER_API_KEY to enable).")
            if site_key != current_key
            else "Site key matches current key."
        ),
    )


def ensure_valid_cineplex_key(current_key: str | None) -> tuple[str | None, KeyRefreshResult | None]:
    """Give collection runs a working key, refreshing automatically if needed.

    Returns ``(key_to_use, refresh_result)``. The refresh result is None when
    the stored key was fine and no refresh was attempted; a failed refresh
    returns the original key so the run fails with the real 401 rather than
    a missing-key error.
    """
    if current_key and validate_key(current_key):
        return current_key, None
    result = refresh_cineplex_key(current_key)
    return result.active_key or current_key, result
