"""Unit tests for the cross-source product matcher.

The matcher is pure — no network, no clock, no DB — so these are fast,
straightforward, and deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aace_execution.connectors._helpers import (
    _jaccard_similarity,
    _tokenize_title,
)
from aace_execution.connectors.base import NormalizedListing
from aace_execution.pipeline.cross_source_matcher import (
    MatchGroup,
    match_cross_source,
    match_cross_source_by_tokens,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_OBSERVED_AT = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)


def _mk_listing(
    source: str,
    listing_id_suffix: str,
    product_key: str,
    *,
    price: float = 100.0,
    title: str = "Test Product",
) -> NormalizedListing:
    """Build a NormalizedListing fixture quickly."""
    return NormalizedListing(
        source=source,
        listing_id=f"{source}:{listing_id_suffix}",
        external_id=listing_id_suffix,
        product_key=product_key,
        title=title,
        url=f"https://{source}.example.com/{listing_id_suffix}",
        price=price,
        currency="USD",
        observed_at=_FIXED_OBSERVED_AT,
    )


# ---------------------------------------------------------------------------
# match_cross_source() — empty / trivial inputs
# ---------------------------------------------------------------------------


class TestEmptyAndTrivial:
    def test_empty_input_returns_empty(self):
        assert match_cross_source([]) == []

    def test_single_listing_returns_empty(self):
        listings = [_mk_listing("slickdeals", "a", "macbook air")]
        assert match_cross_source(listings) == []

    def test_two_listings_same_source_returns_empty(self):
        """Two listings from one source can't be cross-source — no signal."""
        listings = [
            _mk_listing("slickdeals", "a", "macbook air"),
            _mk_listing("slickdeals", "b", "macbook air"),
        ]
        assert match_cross_source(listings) == []

    def test_two_listings_different_products_returns_empty(self):
        listings = [
            _mk_listing("slickdeals", "a", "macbook air"),
            _mk_listing("dealnews", "x", "ipad pro"),
        ]
        assert match_cross_source(listings) == []


# ---------------------------------------------------------------------------
# match_cross_source() — happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_two_sources_same_product_returns_one_group(self):
        listings = [
            _mk_listing("slickdeals", "a", "macbook air"),
            _mk_listing("dealnews", "x", "macbook air"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].product_key == "macbook air"
        assert groups[0].listing_count == 2
        assert groups[0].source_count == 2

    def test_three_sources_same_product(self):
        listings = [
            _mk_listing("slickdeals", "a", "macbook air"),
            _mk_listing("dealnews", "x", "macbook air"),
            _mk_listing("reddit", "p", "macbook air"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].source_count == 3
        assert groups[0].listing_count == 3
        assert groups[0].sources == frozenset({"slickdeals", "dealnews", "reddit"})

    def test_two_sources_multiple_listings_each_for_same_product(self):
        """Two listings per source, all same product -> one group with 4 listings."""
        listings = [
            _mk_listing("slickdeals", "a", "macbook"),
            _mk_listing("slickdeals", "b", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
            _mk_listing("dealnews", "y", "macbook"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].listing_count == 4
        assert groups[0].source_count == 2

    def test_mixed_input_emits_only_cross_source_groups(self):
        """Real-world shape: one matched product + a lot of single-source noise."""
        listings = [
            # Cross-source bucket
            _mk_listing("slickdeals", "m1", "macbook air"),
            _mk_listing("dealnews", "m2", "macbook air"),
            # Single-source noise that must be dropped
            _mk_listing("slickdeals", "n1", "random gadget"),
            _mk_listing("slickdeals", "n2", "another thing"),
            _mk_listing("dealnews", "n3", "yet another"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].product_key == "macbook air"


# ---------------------------------------------------------------------------
# match_cross_source() — filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_listings_with_empty_product_key_are_skipped(self):
        listings = [
            _mk_listing("slickdeals", "a", ""),
            _mk_listing("dealnews", "x", ""),
        ]
        assert match_cross_source(listings) == []

    def test_empty_key_does_not_pollute_real_buckets(self):
        listings = [
            _mk_listing("slickdeals", "a", ""),
            _mk_listing("slickdeals", "b", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].listing_count == 2  # the empty-key one is dropped

    def test_min_sources_3_with_only_2_sources_returns_empty(self):
        listings = [
            _mk_listing("slickdeals", "a", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
        ]
        assert match_cross_source(listings, min_sources=3) == []

    def test_min_sources_3_with_3_sources_returns_group(self):
        listings = [
            _mk_listing("slickdeals", "a", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
            _mk_listing("reddit", "p", "macbook"),
        ]
        groups = match_cross_source(listings, min_sources=3)
        assert len(groups) == 1

    def test_invalid_min_sources_raises(self):
        with pytest.raises(ValueError):
            match_cross_source([], min_sources=0)


# ---------------------------------------------------------------------------
# match_cross_source() — determinism / ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_groups_sorted_by_product_key(self):
        listings = [
            _mk_listing("slickdeals", "z", "zebra phone"),
            _mk_listing("dealnews", "z", "zebra phone"),
            _mk_listing("slickdeals", "a", "apple watch"),
            _mk_listing("dealnews", "a", "apple watch"),
        ]
        groups = match_cross_source(listings)
        assert [g.product_key for g in groups] == ["apple watch", "zebra phone"]

    def test_listings_within_group_sorted_by_source_then_id(self):
        listings = [
            _mk_listing("slickdeals", "z", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
            _mk_listing("dealnews", "a", "macbook"),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        sorted_ids = [listing.listing_id for listing in groups[0].listings]
        # Sort key is (source, listing_id):
        #   dealnews:dealnews:a -> dealnews:a
        #   dealnews:dealnews:x -> dealnews:x
        #   slickdeals:slickdeals:z -> slickdeals:z
        assert sorted_ids == ["dealnews:a", "dealnews:x", "slickdeals:z"]

    def test_input_order_does_not_affect_output(self):
        """Same listings in two different orders -> identical output."""
        listings_a = [
            _mk_listing("slickdeals", "a", "macbook"),
            _mk_listing("dealnews", "x", "macbook"),
            _mk_listing("slickdeals", "b", "ipad"),
            _mk_listing("dealnews", "y", "ipad"),
        ]
        listings_b = list(reversed(listings_a))
        groups_a = match_cross_source(listings_a)
        groups_b = match_cross_source(listings_b)
        assert [g.product_key for g in groups_a] == [g.product_key for g in groups_b]
        assert [
            tuple(listing.listing_id for listing in g.listings) for g in groups_a
        ] == [
            tuple(listing.listing_id for listing in g.listings) for g in groups_b
        ]


# ---------------------------------------------------------------------------
# MatchGroup properties
# ---------------------------------------------------------------------------


class TestMatchGroupProperties:
    def test_is_cross_source_true_for_two_sources(self):
        group = MatchGroup(
            product_key="macbook",
            listings=(
                _mk_listing("slickdeals", "a", "macbook"),
                _mk_listing("dealnews", "x", "macbook"),
            ),
        )
        assert group.is_cross_source is True

    def test_is_cross_source_false_for_single_source(self):
        group = MatchGroup(
            product_key="macbook",
            listings=(_mk_listing("slickdeals", "a", "macbook"),),
        )
        assert group.is_cross_source is False

    def test_sources_returns_unique_set(self):
        """Duplicate sources collapse: 2 slickdeals + 1 dealnews -> 2 distinct sources."""
        group = MatchGroup(
            product_key="macbook",
            listings=(
                _mk_listing("slickdeals", "a", "macbook"),
                _mk_listing("slickdeals", "b", "macbook"),
                _mk_listing("dealnews", "x", "macbook"),
            ),
        )
        assert group.sources == frozenset({"slickdeals", "dealnews"})
        assert group.source_count == 2
        assert group.listing_count == 3

    def test_match_group_equality_works_for_caching(self):
        """Two groups built from the same data compare equal (frozen dataclass).

        We can't use the group as a set element because ``NormalizedListing``
        carries a ``dict`` ``extra`` field, which breaks ``__hash__``.
        Equality is what the worker actually needs for change detection
        between scheduler ticks — hashability isn't required.
        """
        listings = (_mk_listing("slickdeals", "a", "macbook"),)
        group1 = MatchGroup(product_key="macbook", listings=listings)
        group2 = MatchGroup(product_key="macbook", listings=listings)
        assert group1 == group2


# ---------------------------------------------------------------------------
# Realistic end-to-end scenario
# ---------------------------------------------------------------------------


class TestRealisticPipeline:
    def test_slickdeals_and_dealnews_macbook_overlap(self):
        """The exact scenario the matcher exists to solve:

        Slickdeals and DealNews both surface a MacBook deal whose
        product_keys match — the matcher pairs them so the pipeline
        can compare prices.

        Cross-source title-normalization parity is tested in the
        connector tests (see test_run_cross_source_overlap_with_slickdeals
        in test_dealnews_connector.py). The matcher's job is purely
        bucketing — we inject identical product_keys here so this test
        stays focused on what the matcher actually does.
        """
        # The shared product_key — what both connectors would emit in
        # production after their normalize() step.
        shared_key = "apple macbook air 13 m3 8gb 256gb"

        listings = [
            _mk_listing(
                "slickdeals",
                "sd-1",
                shared_key,
                price=799.0,
                title='Apple MacBook Air 13" M3 8GB 256GB $799 + Free Shipping',
            ),
            _mk_listing(
                "dealnews",
                "dn-1",
                shared_key,
                price=799.0,
                title='Apple MacBook Air 13" M3 8GB 256GB for $799 + free shipping',
            ),
        ]
        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].source_count == 2
        assert groups[0].is_cross_source
        # Both listings preserved so downstream can compare prices.
        prices = {listing.price for listing in groups[0].listings}
        assert prices == {799.0}

    def test_realistic_noisy_batch_extracts_one_match_from_dozens(self):
        """Simulate a real scheduler tick: dozens of listings from both
        connectors, only one product happens to overlap."""
        listings = []
        # 20 single-source slickdeals items
        for i in range(20):
            listings.append(
                _mk_listing("slickdeals", f"sd-{i}", f"slickdeals product {i}")
            )
        # 20 single-source dealnews items
        for i in range(20):
            listings.append(
                _mk_listing("dealnews", f"dn-{i}", f"dealnews product {i}")
            )
        # The one overlap
        listings.append(_mk_listing("slickdeals", "sd-match", "shared macbook air m3"))
        listings.append(_mk_listing("dealnews", "dn-match", "shared macbook air m3"))

        groups = match_cross_source(listings)
        assert len(groups) == 1
        assert groups[0].product_key == "shared macbook air m3"
        assert groups[0].source_count == 2


# ---------------------------------------------------------------------------
# Token helpers (_tokenize_title, _jaccard_similarity)
# ---------------------------------------------------------------------------


def _mk_titled(
    source: str,
    listing_id_suffix: str,
    title: str,
    *,
    price: float = 100.0,
) -> NormalizedListing:
    """Like _mk_listing but with an explicit title (and weak product_key)."""
    return NormalizedListing(
        source=source,
        listing_id=f"{source}:{listing_id_suffix}",
        external_id=listing_id_suffix,
        product_key="unused",
        title=title,
        url=f"https://{source}.example.com/{listing_id_suffix}",
        price=price,
        currency="USD",
        observed_at=_FIXED_OBSERVED_AT,
    )


class TestTokenizeTitle:
    def test_empty_title_returns_empty_set(self):
        assert _tokenize_title("") == frozenset()

    def test_lowercases_and_drops_stopwords(self):
        tokens = _tokenize_title("Apple MacBook Air M3 256GB")
        assert tokens == frozenset({"apple", "macbook", "air", "m3", "256gb"})

    def test_strips_prices(self):
        tokens = _tokenize_title('MacBook Air M3 256GB $799 + Free Shipping')
        assert "799" not in tokens
        assert "macbook" in tokens

    def test_strips_was_clause(self):
        tokens = _tokenize_title('Headphones $49.99 (was $129)')
        assert "129" not in tokens
        assert "headphones" in tokens

    def test_strips_parenthetical_asides(self):
        tokens = _tokenize_title('Apple iPad (Early 2025, Silver)')
        assert "early" not in tokens
        assert "silver" not in tokens
        assert "ipad" in tokens

    def test_two_variants_of_same_title_produce_identical_tokens(self):
        """The whole point of this helper — wording shouldn't matter."""
        a = _tokenize_title('Apple MacBook Air M3 256GB $799 + Free Shipping')
        b = _tokenize_title('Apple MacBook Air M3 256GB for $799 free shipping')
        assert a == b

    def test_short_tokens_filtered(self):
        # Single chars dropped (length < 2 filter)
        tokens = _tokenize_title("a b cd ef")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" in tokens
        assert "ef" in tokens


class TestJaccardSimilarity:
    def test_identical_sets_yield_one(self):
        s = frozenset({"a", "b", "c"})
        assert _jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets_yield_zero(self):
        a = frozenset({"a", "b"})
        b = frozenset({"c", "d"})
        assert _jaccard_similarity(a, b) == 0.0

    def test_both_empty_yields_zero(self):
        assert _jaccard_similarity(frozenset(), frozenset()) == 0.0

    def test_one_empty_yields_zero(self):
        assert _jaccard_similarity(frozenset({"a"}), frozenset()) == 0.0

    def test_known_overlap(self):
        # 2 shared / 4 union -> 0.5
        a = frozenset({"x", "y", "z"})
        b = frozenset({"y", "z", "w"})
        assert _jaccard_similarity(a, b) == 0.5


# ---------------------------------------------------------------------------
# match_cross_source_by_tokens — empty / trivial inputs
# ---------------------------------------------------------------------------


class TestTokenMatcherEmptyAndTrivial:
    def test_empty_input_returns_empty(self):
        assert match_cross_source_by_tokens([]) == []

    def test_listings_with_empty_tokens_dropped(self):
        # A title with only stopwords + prices produces no tokens.
        listings = [
            _mk_titled("a", "1", "$10 for free"),
            _mk_titled("b", "2", "$10 for free"),
        ]
        assert match_cross_source_by_tokens(listings) == []

    def test_single_source_returns_empty(self):
        listings = [_mk_titled("slickdeals", "1", "Apple MacBook M3 256GB")]
        assert match_cross_source_by_tokens(listings) == []


# ---------------------------------------------------------------------------
# match_cross_source_by_tokens — the headline use case
# ---------------------------------------------------------------------------


class TestTokenMatcherHappyPath:
    def test_two_variants_of_same_title_cluster_across_sources(self):
        """The reason this matcher exists — wording-tolerant matching."""
        listings = [
            _mk_titled(
                "slickdeals",
                "sd-1",
                'Apple MacBook Air M3 256GB $799 + Free Shipping',
                price=799.0,
            ),
            _mk_titled(
                "dealnews",
                "dn-1",
                'Apple MacBook Air M3 256GB for $799 free shipping',
                price=799.0,
            ),
        ]
        groups = match_cross_source_by_tokens(listings)
        assert len(groups) == 1
        assert groups[0].source_count == 2
        assert groups[0].listing_count == 2

    def test_product_key_is_token_intersection_alphabetical(self):
        listings = [
            _mk_titled("a", "1", "Apple MacBook Air M3 256GB"),
            _mk_titled("b", "2", "Apple MacBook Air M3 256GB"),
        ]
        groups = match_cross_source_by_tokens(listings)
        assert len(groups) == 1
        # Tokens: {apple, macbook, air, m3, 256gb} — sorted alphabetically
        assert groups[0].product_key == "256gb air apple m3 macbook"

    def test_clearly_different_products_do_not_cluster(self):
        listings = [
            _mk_titled(
                "slickdeals",
                "sd-1",
                "Apple MacBook Air M3 256GB",
                price=799.0,
            ),
            _mk_titled(
                "dealnews",
                "dn-1",
                "Sony WH-1000XM5 Wireless Headphones",
                price=278.0,
            ),
        ]
        assert match_cross_source_by_tokens(listings) == []

    def test_three_sources_same_product_yields_one_group(self):
        listings = [
            _mk_titled("a", "1", "Samsung 990 Pro 2TB SSD"),
            _mk_titled("b", "2", "Samsung 990 Pro 2TB SSD"),
            _mk_titled("c", "3", "Samsung 990 Pro 2TB SSD"),
        ]
        groups = match_cross_source_by_tokens(listings)
        assert len(groups) == 1
        assert groups[0].source_count == 3


# ---------------------------------------------------------------------------
# match_cross_source_by_tokens — threshold tuning
# ---------------------------------------------------------------------------


class TestTokenMatcherThresholds:
    def test_high_threshold_rejects_partial_overlap(self):
        listings = [
            _mk_titled("a", "1", "Apple MacBook Air M3 256GB"),
            _mk_titled("b", "2", "Apple MacBook Air M2 512GB"),
        ]
        # Jaccard: intersection {apple, macbook, air} / union {apple, macbook, air, m3, 256gb, m2, 512gb} = 3/7 ≈ 0.43
        groups = match_cross_source_by_tokens(listings, similarity_threshold=0.9)
        assert groups == []

    def test_low_threshold_allows_partial_overlap(self):
        listings = [
            _mk_titled("a", "1", "Apple MacBook Air M3 256GB"),
            _mk_titled("b", "2", "Apple MacBook Air M2 512GB"),
        ]
        groups = match_cross_source_by_tokens(listings, similarity_threshold=0.3)
        assert len(groups) == 1

    def test_invalid_similarity_rejected(self):
        with pytest.raises(ValueError):
            match_cross_source_by_tokens([], similarity_threshold=1.5)
        with pytest.raises(ValueError):
            match_cross_source_by_tokens([], similarity_threshold=-0.1)


# ---------------------------------------------------------------------------
# match_cross_source_by_tokens — realistic batch
# ---------------------------------------------------------------------------


class TestTokenMatcherRealistic:
    def test_real_world_wording_variation(self):
        """Exact phrasing differs between sources — token matcher still pairs."""
        listings = [
            _mk_titled(
                "slickdeals",
                "sd-1",
                'Apple MacBook Air 13" M3 8GB 256GB $799 + Free Shipping',
                price=799.0,
            ),
            _mk_titled(
                "dealnews",
                "dn-1",
                'Apple MacBook Air 13" M3 8GB 256GB for $799 + free shipping',
                price=799.0,
            ),
            # Noise: a different product in only one source
            _mk_titled(
                "slickdeals",
                "sd-2",
                "Cricut Beveled Blank Mug 2-Pack",
                price=4.0,
            ),
        ]
        groups = match_cross_source_by_tokens(listings)
        assert len(groups) == 1
        prices = sorted(listing.price for listing in groups[0].listings)
        assert prices == [799.0, 799.0]

    def test_determinism_across_input_orderings(self):
        listings_a = [
            _mk_titled("slickdeals", "sd-1", "Apple MacBook Air M3 256GB"),
            _mk_titled("dealnews",   "dn-1", "Apple MacBook Air M3 256GB"),
            _mk_titled("slickdeals", "sd-2", "Sony WH-1000XM5 Headphones"),
            _mk_titled("dealnews",   "dn-2", "Sony WH-1000XM5 Headphones"),
        ]
        listings_b = list(reversed(listings_a))
        groups_a = match_cross_source_by_tokens(listings_a)
        groups_b = match_cross_source_by_tokens(listings_b)
        assert [g.product_key for g in groups_a] == [
            g.product_key for g in groups_b
        ]
