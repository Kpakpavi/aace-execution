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


# ---------------------------------------------------------------------------
# Token-set helpers (used by the token-based cross-source matcher).
# ---------------------------------------------------------------------------

# Filler words that don't help distinguish products. Stripped before
# computing the token set so titles like "MacBook ... $799" and
# "MacBook ... for $799 + free shipping" cluster despite different
# surrounding language.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by",
    "for", "from", "with", "without", "into", "via", "vs",
    "free", "shipping", "ship", "shipped", "delivery", "delivered",
    "code", "coupon", "promo", "deal", "deals", "sale", "sales",
    "off", "save", "saving", "savings", "discount", "discounted",
    "today", "only", "limited", "time", "exclusive",
    "open", "box", "refurb", "refurbished",
    "buy", "get", "now",
    "pickup", "pick", "up",
    "prime", "members", "membership", "select", "accounts", "account",
})

# Match price-like substrings so they don't pollute the token set.
# Covers: "$1,299", "$ 49.99", "$799", "30% off", "(was $399)".
_PRICE_LIKE_RE = re.compile(
    r"\$\s?[\d,]+(?:\.\d+)?|\d+\s*%\s*off|\(was\s+\$[\d,.]+\)",
    flags=re.IGNORECASE,
)

# Match parenthetical asides like "(Early 2025, Silver)" — usually
# noise that hurts more than it helps in cross-source matching.
_PAREN_RE = re.compile(r"\([^)]*\)")

# Extract alphanumeric runs (a token).
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize_title(title: str) -> frozenset[str]:
    """Reduce a title to a frozenset of distinguishing tokens.

    Used by ``cross_source_matcher.match_cross_source_by_tokens``.
    Strips prices, parenthetical asides, and stopwords so two titles
    for the same product produce largely overlapping sets even when
    their surrounding wording differs.

    Examples:
        "Apple MacBook Air M3 256GB $799 + Free Shipping"
            -> {apple, macbook, air, m3, 256gb}
        "Apple MacBook Air M3 256GB for $799 free shipping"
            -> {apple, macbook, air, m3, 256gb}

    Jaccard similarity of the two sets above is 1.0 — they cluster.
    """
    if not title:
        return frozenset()
    text = title.lower()
    text = _PRICE_LIKE_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)
    return frozenset(
        token
        for token in _TOKEN_RE.findall(text)
        if len(token) >= 2 and token not in _STOPWORDS
    )


def _jaccard_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Return |A ∩ B| / |A ∪ B|. Returns 0.0 when both sides are empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
