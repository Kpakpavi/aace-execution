"""Cross-source product matcher.

Each connector emits ``NormalizedListing`` objects independently — every
listing is just one deal observation from one source. To detect price
discrepancies (the whole point of the pipeline) we first need to find
listings that describe the *same product* across multiple sources.

This module does that grouping. It is intentionally simple for v0.1:
listings are bucketed by their ``product_key`` (the lowercase normalized
title produced by each connector, via ``connectors._helpers``). A
bucket is "cross-source" iff it contains listings from at least N
distinct sources (default: 2 — the only useful value right now, since
the pipeline's discrepancy detector needs two observations to fire).

Buckets that don't meet the threshold are dropped — they have nothing
to compare against, so there's no discrepancy to score.

Post-v0.1.0 work will replace the title-key heuristic with stronger
product identifiers (GTIN / UPC / ASIN extraction). The contract here
stays the same — only the key-derivation logic gets smarter.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from aace_execution.connectors.base import NormalizedListing

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchGroup:
    """A bucket of listings that all describe the same product.

    A group is "cross-source" iff its ``sources`` set has 2+ distinct
    entries. The pipeline only acts on cross-source groups because the
    discrepancy detector needs at least two observations to fire.

    ``listings`` is a tuple (not a list) so the dataclass stays
    immutable — useful for caching and clean equality semantics.
    (Note: ``NormalizedListing`` has a ``dict`` ``extra`` field, so the
    group is NOT hashable; dedupe via ``product_key`` if you need it.)
    """

    product_key: str
    listings: tuple[NormalizedListing, ...]

    @property
    def sources(self) -> frozenset[str]:
        """Distinct source names present in this group."""
        return frozenset(listing.source for listing in self.listings)

    @property
    def is_cross_source(self) -> bool:
        """True iff listings come from at least 2 distinct sources."""
        return len(self.sources) >= 2

    @property
    def listing_count(self) -> int:
        return len(self.listings)

    @property
    def source_count(self) -> int:
        return len(self.sources)


def match_cross_source(
    listings: Iterable[NormalizedListing],
    *,
    min_sources: int = 2,
) -> list[MatchGroup]:
    """Bucket listings by product_key, keep only cross-source groups.

    Args:
        listings: Flat sequence of normalized listings from any number
            of connectors. Order doesn't matter.
        min_sources: Minimum distinct source count for a group to be
            emitted. Default 2. Use 3+ only if you want stricter
            confirmation across many sources.

    Returns:
        A list of ``MatchGroup`` objects, sorted by ``product_key`` for
        determinism. Single-source buckets and listings with empty
        ``product_key`` are filtered out.

    Notes:
        - The matcher is pure: same input -> same output, no I/O, no
          time-of-day dependency. Safe to call from any thread.
        - Cost is O(N log N) on the number of input listings (the
          sort dominates the dict bucketing). For thousands of
          listings per tick this is still well under a millisecond.
    """
    if min_sources < 1:
        raise ValueError(f"min_sources must be >= 1, got {min_sources!r}")

    buckets: dict[str, list[NormalizedListing]] = defaultdict(list)
    total_input = 0
    skipped_empty_key = 0

    for listing in listings:
        total_input += 1
        if not listing.product_key:
            skipped_empty_key += 1
            continue
        buckets[listing.product_key].append(listing)

    groups: list[MatchGroup] = []
    for product_key in sorted(buckets):
        bucket = buckets[product_key]
        # Sort listings within a group for deterministic output —
        # helpful in tests, helpful for diffable logs.
        bucket_sorted = sorted(
            bucket, key=lambda listing: (listing.source, listing.listing_id)
        )
        distinct_sources = {listing.source for listing in bucket_sorted}
        if len(distinct_sources) < min_sources:
            continue
        groups.append(
            MatchGroup(
                product_key=product_key,
                listings=tuple(bucket_sorted),
            )
        )

    logger.info(
        "cross_source_match_complete",
        extra={
            "input_listings": total_input,
            "skipped_empty_key": skipped_empty_key,
            "total_buckets": len(buckets),
            "cross_source_groups": len(groups),
            "min_sources": min_sources,
        },
    )

    return groups
