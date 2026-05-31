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

from aace_execution.connectors._helpers import (
    _jaccard_similarity,
    _tokenize_title,
)
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


# ---------------------------------------------------------------------------
# Token-based matcher (post-v0.1.0 upgrade — see _helpers._tokenize_title).
# ---------------------------------------------------------------------------


def match_cross_source_by_tokens(
    listings: Iterable[NormalizedListing],
    *,
    min_sources: int = 2,
    similarity_threshold: float = 0.6,
) -> list[MatchGroup]:
    """Cross-source match using token-set + Jaccard similarity.

    The exact-key matcher (``match_cross_source`` above) misses real
    overlaps when titles differ by even a single filler word — e.g.
    "MacBook ... $799" vs "MacBook ... for $799 free shipping". This
    function tolerates that by:

        1. Converting each title to a set of tokens (stopwords + price
           noise stripped — see ``_tokenize_title``).
        2. Clustering listings whose pairwise Jaccard similarity meets
           ``similarity_threshold``, via union-find.
        3. Returning only clusters with at least ``min_sources``
           distinct sources.

    Args:
        listings: flat sequence of normalized listings from any number
            of connectors. Order doesn't matter.
        min_sources: drop clusters below this many distinct sources.
            Default 2 — the only value that makes sense for v0.1.0.
        similarity_threshold: Jaccard cutoff for two titles to cluster.
            Default 0.6 — a middle ground between false positives
            (very different products clustering) and false negatives
            (same product missed because wording differs too much).
            Raise to 0.75+ for stricter matching; lower to 0.4 to see
            more candidate matches.

    Returns:
        Sorted list of ``MatchGroup`` objects. Each group's
        ``product_key`` is the intersection of token sets in the
        cluster (alphabetically joined) — stable across runs and
        useful as a dedup key downstream.

    Complexity:
        O(N²) on the number of listings (pairwise Jaccard) +
        O(α(N)) per union-find op. For hundreds of listings per tick
        this is still sub-millisecond on any modern CPU.
    """
    if min_sources < 1:
        raise ValueError(f"min_sources must be >= 1, got {min_sources!r}")
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError(
            f"similarity_threshold must be in [0, 1], "
            f"got {similarity_threshold!r}"
        )

    # Build (listing, tokens) pairs, dropping listings with empty token sets
    # (no useful content to match on — e.g. all stopwords or unparseable).
    items: list[tuple[NormalizedListing, frozenset[str]]] = []
    for listing in listings:
        tokens = _tokenize_title(listing.title)
        if tokens:
            items.append((listing, tokens))

    n = len(items)
    if n == 0:
        return []

    # Union-Find with path compression. parent[i] points to a representative
    # in i's cluster; following the chain eventually reaches the root.
    parent = list(range(n))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Pairwise comparison: link any two listings whose token sets are
    # similar enough. This is the only O(N²) step.
    for i in range(n):
        ti = items[i][1]
        for j in range(i + 1, n):
            tj = items[j][1]
            if _jaccard_similarity(ti, tj) >= similarity_threshold:
                union(i, j)

    # Group items by cluster root.
    clusters: dict[int, list[tuple[NormalizedListing, frozenset[str]]]] = (
        defaultdict(list)
    )
    for i in range(n):
        clusters[find(i)].append(items[i])

    groups: list[MatchGroup] = []
    for cluster in clusters.values():
        sources = {listing.source for listing, _ in cluster}
        if len(sources) < min_sources:
            continue

        cluster_listings = [listing for listing, _ in cluster]
        cluster_tokens = [tokens for _, tokens in cluster]

        # Derive a stable canonical product_key from the intersection
        # of token sets across the cluster. This is what downstream
        # uses for dedup and human-readable identification.
        common = cluster_tokens[0]
        for ts in cluster_tokens[1:]:
            common = common & ts

        if common:
            product_key = " ".join(sorted(common))
        else:
            # Cluster of similar-but-non-identical token sets. Fall back
            # to the listing.product_key of the shortest title (most
            # information-dense, typically).
            product_key = min(
                cluster_listings,
                key=lambda listing: (len(listing.title), listing.listing_id),
            ).product_key or "match"

        cluster_listings.sort(key=lambda listing: (listing.source, listing.listing_id))
        groups.append(
            MatchGroup(
                product_key=product_key,
                listings=tuple(cluster_listings),
            )
        )

    groups.sort(key=lambda g: g.product_key)

    logger.info(
        "cross_source_token_match_complete",
        extra={
            "input_listings": n,
            "clusters_total": len(clusters),
            "cross_source_groups": len(groups),
            "min_sources": min_sources,
            "similarity_threshold": similarity_threshold,
        },
    )
    return groups
