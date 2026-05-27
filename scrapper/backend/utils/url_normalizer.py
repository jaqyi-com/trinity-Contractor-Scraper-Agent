# utils/url_normalizer.py
# Production scraper pattern: strip www, trailing slash, query strings.
# Extract bare domain for dedup.

from urllib.parse import urlparse, urljoin
from typing import Optional


def normalize_url(base: str, href: str) -> str:
    """Normalize href relative to base. Empty string when invalid."""
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        href = "http:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    try:
        return urljoin(base, href)
    except Exception:
        return ""


def normalize_website(url: Optional[str]) -> Optional[str]:
    """Lowercase, https, strip www + trailing slash + query."""
    if not url:
        return None
    u = url.strip().lower()
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    parsed = urlparse(u)
    host = parsed.netloc.replace("www.", "")
    return f"https://{host}{parsed.path.rstrip('/')}"


def extract_domain(url: Optional[str]) -> Optional[str]:
    """Bare domain for dedup, e.g. 'example.com'."""
    if not url:
        return None
    u = url.strip().lower()
    if not (u.startswith("http://") or u.startswith("https://")):
        u = "https://" + u
    host = urlparse(u).netloc.replace("www.", "")
    return host or None
