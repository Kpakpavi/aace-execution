"""Shared parsing helpers used across connectors.

Internal to the connectors package — names are leading-underscored to
signal "not part of the public API." Promoted out of ``slickdeals.py``
on Day 2 when the Reddit connector needed the same primitives.

Day 3+ will likely add stronger product-key extraction here
(GTIN / UPC / ASIN), keeping the fallback title-normalization for
sources that don't expose strong identifiers.
"""

from __future__ import annotations

import re

# Matches "$1,299", "$ 49.99", "$799" — captures the numeric portion.
_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")

# Strip everything that isn't lowercase alphanumeric for a coarse product key.
_TITLE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _extract_price(text: str) -> float | None:
    """Pull the first plausible USD price out of a deal title.

    Examples:
        "MacBook Air $799 + Free Shipping"           -> 799.0
        "Big TV $1,299"                              -> 1299.0
        "Headphones $49.99 (was $129)"               -> 49.99
        "Free Sample of Soap"                        -> None
    """
    match = _PRICE_RE.search(text)
    if not match:
        return None
    cleaned = match.group(1).replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_title(title: str) -> str:
    """Reduce a deal title to a coarse cross-source product key.

    Intentionally lossy: lowercase, alphanumeric, single spaces. Day 3
    work will add stronger keys (GTIN/UPC/ASIN extraction) on top of
    this fallback.
    """
    return _TITLE_NORMALIZE_RE.sub(" ", title.lower()).strip()
