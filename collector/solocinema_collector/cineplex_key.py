"""Re-read Cineplex's public API key when the one we hold is rejected.

Cineplex ships its Azure APIM subscription key inside its public web-client
JS bundles, and rotates it now and then. Our stored key (the
CINEPLEX_SUBSCRIPTION_KEY secret) then starts returning 401s. This reads the
current key the same way a browser gets it: fetch the homepage, follow the
Next.js chunk script tags, and scan the bundles for the key. A candidate is
only adopted after it passes a live probe.

The refreshed key is used for the rest of the run only; the stored secret
isn't rewritten, so each later run repeats the cheap refresh until someone
updates it (the run output flags this). Adapted from the unmerged PR #4,
which wrote the key back to Render before the collector moved to Actions.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .url_guard import require_allowed_url


CINEPLEX_HOME_URL = "https://www.cineplex.com/"
# Any cheap authenticated endpoint works as a probe; Southland showtimes is the
# same call discovery makes first anyway.
KEY_PROBE_URL = (
    "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes"
    "?language=en&locationId=4108"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_CHUNK_URL = re.compile(
    r'src="(https://www\.cineplex\.com/next-static-files/_next/static/chunks/[^"]+\.js)"'
)
# The key appears both in runtime config objects and inline request headers.
_KEY_PATTERNS = (
    re.compile(r'ocpApimSubscriptionKey\s*:\s*"([0-9a-f]{32})"'),
    re.compile(r'"Ocp-Apim-Subscription-Key"\s*:\s*"([0-9a-f]{32})"'),
)

Fetcher = Callable[[str], str]


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
    """The subscription key the Cineplex web client currently ships.

    The bundles reference more than one key (e.g. a separate one for the
    smart-app-banner endpoint); the theatrical-API key dominates by
    occurrence count, so the most common key wins.
    """
    home = fetch(CINEPLEX_HOME_URL)
    counts = extract_subscription_keys(home)
    for chunk_url in dict.fromkeys(_CHUNK_URL.findall(home)):
        try:
            counts.update(extract_subscription_keys(fetch(chunk_url)))
        except (OSError, ValueError):
            continue  # a missing chunk must not sink the whole scan
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def validate_key(key: str, probe_url: str = KEY_PROBE_URL) -> bool:
    """True when the live showtimes endpoint accepts the key."""
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


def refreshed_key(
    rejected_key: str | None,
    fetch: Fetcher = _fetch_text,
    validate: Callable[[str], bool] = validate_key,
) -> str | None:
    """A working key different from `rejected_key`, or None if there isn't one.

    None when the site still ships the rejected key (an outage rather than a
    rotation) or its key fails the live probe too; the caller then lets the
    original 401 stand.
    """
    try:
        site_key = fetch_site_key(fetch)
    except (OSError, ValueError):
        return None
    if site_key is None or site_key == rejected_key:
        return None
    return site_key if validate(site_key) else None
