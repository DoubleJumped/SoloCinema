from __future__ import annotations

from urllib.parse import urlsplit


# Registrable domains this collector is allowed to fetch from. Scraped URLs are
# checked against this allowlist before any network request so a hostile payload
# cannot redirect a fetch at an arbitrary host or a file:// path.
ALLOWED_FETCH_DOMAINS = (
    "atomtickets.com",
    "cineplex.com",
    "landmarkcinemas.com",
    "sasksciencecentre.com",
    "ticketclick.com",
)


def is_http_url(url: str | None) -> bool:
    """True when the URL parses with an http or https scheme."""
    if not url:
        return False
    return urlsplit(url).scheme in ("http", "https")


def require_allowed_url(url: str) -> str:
    """Raise unless the URL is https and its host is in the allowlist."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValueError(f"Refusing to fetch non-https URL: {url!r}")
    host = (parts.hostname or "").lower()
    if not any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_FETCH_DOMAINS
    ):
        raise ValueError(f"Refusing to fetch URL outside the allowlist: {url!r}")
    return url
