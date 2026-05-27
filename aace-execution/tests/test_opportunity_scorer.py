"""Unit tests for the v0.1.0 opportunity scorer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aace_execution.connectors.base import NormalizedListing
from aace_execution.pipeline.cross_source_matcher import MatchGroup
from aace_execution.pipeline.opportunity_scorer import (
    OpportunityScorer,
    ScoredOpportunity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


def _mk_listing(source: str, price: float, *, lid_suffix: str = "a") -> NormalizedListing:
    return NormalizedListing(
        source=source,
        listing_id=f"{source}:{lid_suffix}",
        external_id=lid_suffix,
        product_key="apple macbook air m3",
        title="Apple MacBook Air M3",
        url=f"https://{source}.example.com/{lid_suffix}",
        price=price,
        currency="USD",
        observed_at=_FIXED_NOW,
    )


def _mk_group(*listings: NormalizedListing) -> MatchGroup:
    return MatchGroup(
        product_key=listings[0].product_key if listings else "",
        listings=tuple(listings),
    )


def _fixed_now() -> datetime:
    return _FIXED_NOW


# ---------------------------------------------------------------------------
# Single-source / empty inputs
# ---------------------------------------------------------------------------


class TestRejectsNonCrossSource:
    def test_single_source_group_returns_none(self):
        scorer = OpportunityScorer()
        group = _mk_group(_mk_listing("slickdeals", 800.0))
        assert scorer.score(group) is None

    def test_empty_listings_returns_none(self):
        scorer = OpportunityScorer()
        # Two-source MatchGroup not constructible without listings, but
        # an empty tuple is technically allowed. Make sure we no-op safely.
        group = MatchGroup(product_key="x", listings=())
        assert scorer.score(group) is None

    def test_negative_max_price_returns_none(self):
        scorer = OpportunityScorer()
        group = _mk_group(
            _mk_listing("slickdeals", -10.0, lid_suffix="a"),
            _mk_listing("dealnews", -20.0, lid_suffix="b"),
        )
        assert scorer.score(group) is None

    def test_zero_max_price_returns_none(self):
        scorer = OpportunityScorer()
        group = _mk_group(
            _mk_listing("slickdeals", 0.0, lid_suffix="a"),
            _mk_listing("dealnews", 0.0, lid_suffix="b"),
        )
        assert scorer.score(group) is None


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------


class TestThresholds:
    def test_skips_below_absolute_threshold(self):
        scorer = OpportunityScorer(
            min_absolute_spread=10.0, min_percent_spread=0.0
        )
        group = _mk_group(
            _mk_listing("slickdeals", 100.0, lid_suffix="a"),
            _mk_listing("dealnews", 105.0, lid_suffix="b"),  # $5 spread
        )
        assert scorer.score(group) is None

    def test_skips_below_percent_threshold(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.10
        )
        group = _mk_group(
            _mk_listing("slickdeals", 100.0, lid_suffix="a"),
            _mk_listing("dealnews", 105.0, lid_suffix="b"),  # 5% spread
        )
        assert scorer.score(group) is None

    def test_passes_when_both_thresholds_met(self):
        scorer = OpportunityScorer(
            min_absolute_spread=5.0, min_percent_spread=0.05
        )
        group = _mk_group(
            _mk_listing("slickdeals", 100.0, lid_suffix="a"),
            _mk_listing("dealnews", 110.0, lid_suffix="b"),  # $10 / ~9% spread
        )
        assert scorer.score(group) is not None


# ---------------------------------------------------------------------------
# Happy-path math
# ---------------------------------------------------------------------------


class TestScoringMath:
    def test_min_max_spread_calculated(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0, now_fn=_fixed_now
        )
        group = _mk_group(
            _mk_listing("slickdeals", 800.0, lid_suffix="a"),
            _mk_listing("dealnews", 1000.0, lid_suffix="b"),
        )
        opp = scorer.score(group)
        assert opp is not None
        assert opp.min_price == 800.0
        assert opp.max_price == 1000.0
        assert opp.absolute_spread == 200.0
        assert opp.percent_spread == 0.2  # 200/1000

    def test_three_listings_uses_min_and_max(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group = _mk_group(
            _mk_listing("a", 100.0, lid_suffix="1"),
            _mk_listing("b", 120.0, lid_suffix="2"),
            _mk_listing("c", 150.0, lid_suffix="3"),
        )
        opp = scorer.score(group)
        assert opp is not None
        assert opp.min_price == 100.0
        assert opp.max_price == 150.0
        assert opp.absolute_spread == 50.0

    def test_score_scales_with_percent_spread(self):
        # 10% spread with default 2.0 multiplier -> 0.2 score
        scorer = OpportunityScorer(
            min_absolute_spread=0.0,
            min_percent_spread=0.0,
            score_pct_multiplier=2.0,
        )
        group = _mk_group(
            _mk_listing("a", 90.0, lid_suffix="1"),
            _mk_listing("b", 100.0, lid_suffix="2"),  # 10% spread
        )
        opp = scorer.score(group)
        assert opp is not None
        assert abs(opp.score - 0.2) < 1e-9

    def test_score_is_capped_at_one(self):
        # 50% spread * 2.0 multiplier -> 1.0 (capped)
        scorer = OpportunityScorer(
            min_absolute_spread=0.0,
            min_percent_spread=0.0,
            score_pct_multiplier=2.0,
        )
        group = _mk_group(
            _mk_listing("a", 50.0, lid_suffix="1"),
            _mk_listing("b", 100.0, lid_suffix="2"),  # 50% spread
        )
        opp = scorer.score(group)
        assert opp is not None
        assert opp.score == 1.0


# ---------------------------------------------------------------------------
# Opportunity id stability
# ---------------------------------------------------------------------------


class TestOpportunityId:
    def test_same_prices_yields_same_id(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group_a = _mk_group(
            _mk_listing("slickdeals", 800.0, lid_suffix="a"),
            _mk_listing("dealnews", 850.0, lid_suffix="b"),
        )
        group_b = _mk_group(
            _mk_listing("slickdeals", 800.0, lid_suffix="x"),
            _mk_listing("dealnews", 850.0, lid_suffix="y"),
        )
        a = scorer.score(group_a)
        b = scorer.score(group_b)
        assert a is not None and b is not None
        assert a.opportunity_id == b.opportunity_id

    def test_different_prices_yield_different_ids(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group_a = _mk_group(
            _mk_listing("slickdeals", 800.0, lid_suffix="a"),
            _mk_listing("dealnews", 850.0, lid_suffix="b"),
        )
        group_b = _mk_group(
            _mk_listing("slickdeals", 799.0, lid_suffix="a"),
            _mk_listing("dealnews", 850.0, lid_suffix="b"),
        )
        a = scorer.score(group_a)
        b = scorer.score(group_b)
        assert a is not None and b is not None
        assert a.opportunity_id != b.opportunity_id

    def test_id_includes_product_key_and_prices(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group = _mk_group(
            _mk_listing("a", 800.0, lid_suffix="x"),
            _mk_listing("b", 850.0, lid_suffix="y"),
        )
        opp = scorer.score(group)
        assert opp is not None
        assert "apple macbook air m3" in opp.opportunity_id
        assert "800.00" in opp.opportunity_id
        assert "850.00" in opp.opportunity_id


# ---------------------------------------------------------------------------
# Output sources/listings ordering + provenance
# ---------------------------------------------------------------------------


class TestOutputContents:
    def test_sources_sorted_and_unique(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group = _mk_group(
            _mk_listing("zsource", 100.0, lid_suffix="z"),
            _mk_listing("asource", 150.0, lid_suffix="a"),
        )
        opp = scorer.score(group)
        assert opp is not None
        assert opp.sources == ["asource", "zsource"]

    def test_listings_sorted_by_price(self):
        scorer = OpportunityScorer(
            min_absolute_spread=0.0, min_percent_spread=0.0
        )
        group = _mk_group(
            _mk_listing("a", 1000.0, lid_suffix="x"),
            _mk_listing("b", 800.0, lid_suffix="y"),
            _mk_listing("c", 900.0, lid_suffix="z"),
        )
        opp = scorer.score(group)
        assert opp is not None
        assert [listing.price for listing in opp.listings] == [800.0, 900.0, 1000.0]


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_negative_absolute_threshold_rejected(self):
        with pytest.raises(ValueError):
            OpportunityScorer(min_absolute_spread=-1.0)

    def test_negative_percent_threshold_rejected(self):
        with pytest.raises(ValueError):
            OpportunityScorer(min_percent_spread=-0.1)

    def test_zero_multiplier_rejected(self):
        with pytest.raises(ValueError):
            OpportunityScorer(score_pct_multiplier=0.0)


# ---------------------------------------------------------------------------
# Realistic end-to-end vignette
# ---------------------------------------------------------------------------


def test_realistic_macbook_match_produces_meaningful_score():
    """Slickdeals $799 vs DealNews $899 — a real arbitrage signal."""
    scorer = OpportunityScorer(now_fn=_fixed_now)
    group = _mk_group(
        _mk_listing("slickdeals", 799.0, lid_suffix="sd"),
        _mk_listing("dealnews", 899.0, lid_suffix="dn"),
    )
    opp = scorer.score(group)
    assert opp is not None
    assert isinstance(opp, ScoredOpportunity)
    assert opp.min_price == 799.0
    assert opp.max_price == 899.0
    assert abs(opp.absolute_spread - 100.0) < 1e-9
    assert opp.percent_spread > 0.10  # >10% spread
    assert opp.score > 0.20
    assert opp.sources == ["dealnews", "slickdeals"]
    assert opp.detected_at == _FIXED_NOW
