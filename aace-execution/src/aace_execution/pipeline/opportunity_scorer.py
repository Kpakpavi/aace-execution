"""Opportunity scorer (v0.1.0 — simple price-spread).

After the cross-source matcher buckets listings by product, this module
decides whether a bucket represents a real arbitrage opportunity worth
shipping to the agent.

For v0.1.0 the scoring is deliberately simple:

    spread_absolute = max_price - min_price
    spread_percent  = spread_absolute / max_price
    score           = min(1.0, spread_percent * score_pct_multiplier)

A group is *worth shipping* iff both of:
    - spread_absolute >= min_absolute_spread (default $5)
    - spread_percent  >= min_percent_spread (default 5%)

This intentionally skips the existing 6-stage pipeline — its richer
discrepancy/scoring/duplicate-check model is more than v0.1.0 needs.
Post-v0.1.0 will wire to it for production-quality scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from aace_execution.connectors.base import NormalizedListing
from aace_execution.pipeline.cross_source_matcher import MatchGroup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredOpportunity:
    """A cross-source match group that passed the score threshold.

    ``opportunity_id`` is deterministic: same product + same prices =
    same id. This means the webhook's dedup store will correctly skip
    re-sending an unchanged opportunity on subsequent scheduler ticks.
    Price changes produce a new id, so the agent sees fresh info.
    """

    opportunity_id: str
    product_key: str
    listings: list[NormalizedListing] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    min_price: float = 0.0
    max_price: float = 0.0
    absolute_spread: float = 0.0
    percent_spread: float = 0.0
    score: float = 0.0
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class OpportunityScorer:
    """Scores ``MatchGroup`` objects into ``ScoredOpportunity`` or None.

    Thresholds are configurable via constructor; defaults are sensible
    starting points and can be tuned in env-driven config for the
    worker (see ``worker.py``).
    """

    def __init__(
        self,
        *,
        min_absolute_spread: float = 5.0,
        min_percent_spread: float = 0.05,
        score_pct_multiplier: float = 2.0,
        now_fn=None,
    ) -> None:
        if min_absolute_spread < 0:
            raise ValueError("min_absolute_spread must be >= 0")
        if min_percent_spread < 0:
            raise ValueError("min_percent_spread must be >= 0")
        if score_pct_multiplier <= 0:
            raise ValueError("score_pct_multiplier must be > 0")
        self._min_absolute = min_absolute_spread
        self._min_percent = min_percent_spread
        self._score_multiplier = score_pct_multiplier
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def score(self, group: MatchGroup) -> ScoredOpportunity | None:
        """Score a group. Returns ``None`` when below threshold."""
        if not group.is_cross_source:
            return None
        if not group.listings:
            return None

        prices = sorted(listing.price for listing in group.listings)
        min_price = prices[0]
        max_price = prices[-1]

        if max_price <= 0:
            return None  # can't compute percent on zero/negative prices

        absolute_spread = max_price - min_price
        percent_spread = absolute_spread / max_price

        if absolute_spread < self._min_absolute:
            logger.debug(
                "scorer_skip_below_absolute",
                extra={
                    "product_key": group.product_key,
                    "absolute_spread": absolute_spread,
                    "min_absolute": self._min_absolute,
                },
            )
            return None
        if percent_spread < self._min_percent:
            logger.debug(
                "scorer_skip_below_percent",
                extra={
                    "product_key": group.product_key,
                    "percent_spread": percent_spread,
                    "min_percent": self._min_percent,
                },
            )
            return None

        score = min(1.0, percent_spread * self._score_multiplier)

        opportunity_id = (
            f"{group.product_key}|{min_price:.2f}|{max_price:.2f}"
        )

        sources = sorted(group.sources)
        listings_sorted = sorted(
            group.listings, key=lambda l: (l.price, l.source, l.listing_id)
        )

        opp = ScoredOpportunity(
            opportunity_id=opportunity_id,
            product_key=group.product_key,
            listings=listings_sorted,
            sources=sources,
            min_price=min_price,
            max_price=max_price,
            absolute_spread=absolute_spread,
            percent_spread=percent_spread,
            score=score,
            detected_at=self._now_fn(),
        )
        logger.info(
            "scorer_emit_opportunity",
            extra={
                "opportunity_id": opportunity_id,
                "product_key": group.product_key,
                "score": score,
                "absolute_spread": absolute_spread,
                "percent_spread": percent_spread,
            },
        )
        return opp
