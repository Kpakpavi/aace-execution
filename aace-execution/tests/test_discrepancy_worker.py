"""
Unit tests for the Discrepancy Worker.

Mapped to: Contracts/DISCREPANCY_WORKER_CONTRACT.md

Coverage mapping:
    §3, §8          — All three result types (DISCREPANCY_DETECTED, NO_DISCREPANCY, PROCESSING_FAILURE)
    §6.2, §10.3     — Pair construction: no duplicate A/B↔B/A, deterministic lexicographic ordering
    §7.1            — Absolute difference correctness
    §7.2            — Percentage difference using lesser price as denominator
    §7.3            — Threshold logic: ABSOLUTE, PERCENTAGE, BOTH
    §7.5            — Noise filters 1–7 (zero diff, below threshold, same source, etc.)
    §6.4            — Multi-pair: one valid discrepancy triggers overall detection
    §10             — Determinism: same input → same output
    §5, §8.3, §9    — Failure cases: invalid inputs, missing/invalid rule sets
    §10.7           — Boundary semantics: difference == threshold meets it (>=)
"""

from __future__ import annotations

from datetime import datetime

import pytest # type: ignore

from src.aace_execution.workers.discrepancy_worker import (
    DiscrepancyDetectedResult,
    DiscrepancyResultType,
    DiscrepancyWorker,
    NoDiscrepancyResult,
    NoiseFilter,
    ProcessingFailureResult,
    ThresholdMethod,
)

# ---------------------------------------------------------------------------
# Fixed reference values — no system clock
# ---------------------------------------------------------------------------

FIXED_TIMESTAMP = datetime(2025, 6, 15, 12, 0, 0)
FIXED_PIPELINE_ID = "pipe-test-001"
FIXED_PRODUCT_ID = "prod-001"
FIXED_PRODUCT_NAME = "Widget Alpha"
FIXED_RULE_ID = "rule-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs(
    observation_id: str,
    source: str,
    price: float,
    *,
    listing_ref: str = "listing-1",
    observed_at: datetime | None = None,
    product_ref: str | None = None,
    currency: str | None = None,
) -> dict:
    """Build a minimal valid observation dict."""
    obs = {
        "observation_id": observation_id,
        "source": source,
        "normalized_price": price,
        "observed_at": observed_at or FIXED_TIMESTAMP,
        "listing_ref": listing_ref,
    }
    if product_ref is not None:
        obs["product_ref"] = product_ref
    if currency is not None:
        obs["currency"] = currency
    return obs


def _rule_set(
    method: str = ThresholdMethod.ABSOLUTE.value,
    absolute_threshold: float | None = 1.0,
    percentage_threshold: float | None = None,
    rule_id: str = FIXED_RULE_ID,
) -> dict:
    """Build a minimal valid discrepancy rule set."""
    rs: dict = {"rule_id": rule_id, "threshold_method": method}
    if absolute_threshold is not None:
        rs["absolute_threshold"] = absolute_threshold
    if percentage_threshold is not None:
        rs["percentage_threshold"] = percentage_threshold
    return rs


def _context(
    observations: list[dict],
    rule_set: dict | None = None,
    product_id: str = FIXED_PRODUCT_ID,
    product_name: str = FIXED_PRODUCT_NAME,
    pipeline_execution_id: str = FIXED_PIPELINE_ID,
    evaluation_reference_timestamp: datetime | None = None,
) -> dict:
    """Build a full normalized context."""
    return {
        "product_id": product_id,
        "product_name": product_name,
        "observations": observations,
        "discrepancy_rule_set": rule_set or _rule_set(),
        "pipeline_execution_id": pipeline_execution_id,
        "evaluation_reference_timestamp": (
            evaluation_reference_timestamp or FIXED_TIMESTAMP
        ),
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def worker() -> DiscrepancyWorker:
    return DiscrepancyWorker()


# ===================================================================
# 1. Result Types — Contract §8
# ===================================================================

class TestResultTypes:
    """§8: The worker must return exactly one of three result classifications."""

    def test_discrepancy_detected(self, worker: DiscrepancyWorker) -> None:
        """§8.1: Prices far apart → DISCREPANCY_DETECTED."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.result == DiscrepancyResultType.DISCREPANCY_DETECTED.value
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.evaluation_reference_timestamp == FIXED_TIMESTAMP
        assert result.rule_id == FIXED_RULE_ID
        assert result.pairs_with_discrepancy >= 1

    def test_no_discrepancy(self, worker: DiscrepancyWorker) -> None:
        """§8.2: Prices close together → NO_DISCREPANCY."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 10.5),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.result == DiscrepancyResultType.NO_DISCREPANCY.value
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID

    def test_processing_failure(self, worker: DiscrepancyWorker) -> None:
        """§8.3: Missing required field → PROCESSING_FAILURE."""
        ctx = _context(
            observations=[
                _obs("obs-1", "SourceA", 10.0),
                _obs("obs-2", "SourceB", 20.0),
            ],
            product_id="",  # violates §4.1
        )
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert result.result == DiscrepancyResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == "DISCREPANCY_WORKER"
        assert result.retriable is False
        assert len(result.failure_reason) > 0


# ===================================================================
# 2. Pair Construction — Contract §6.2, §10.3
# ===================================================================

class TestPairConstruction:
    """§6.2: No duplicate A/B and B/A. Deterministic lexicographic ordering."""

    def test_no_duplicate_pairs(self, worker: DiscrepancyWorker) -> None:
        """§6.2: (A, B) and (B, A) must not both appear."""
        ctx = _context([
            _obs("obs-1", "SourceB", 10.0),
            _obs("obs-2", "SourceA", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pairs_evaluated == 1
        pair = result.pair_results[0]
        # Canonical: lesser source is always source_a
        assert pair.source_a == "SourceA"
        assert pair.source_b == "SourceB"

    def test_deterministic_ordering_with_three_sources(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.3: Pairs sorted by pair_id (lexicographic source sort)."""
        ctx = _context([
            _obs("obs-1", "Zeta", 10.0),
            _obs("obs-2", "Alpha", 20.0),
            _obs("obs-3", "Mid", 30.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pairs_evaluated == 3
        pair_ids = [pr.pair_id for pr in result.pair_results]
        # Expected canonical pairs sorted: Alpha::Mid, Alpha::Zeta, Mid::Zeta
        assert pair_ids == ["Alpha::Mid", "Alpha::Zeta", "Mid::Zeta"]

    def test_pair_id_format(self, worker: DiscrepancyWorker) -> None:
        """§8.1: pair_id = '{source_a}::{source_b}'."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 50.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].pair_id == "SourceA::SourceB"

    def test_observation_list_order_does_not_affect_pair_ordering(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.3: Pair ordering stable regardless of observation list order."""
        obs_order_1 = [
            _obs("obs-1", "Zeta", 10.0),
            _obs("obs-2", "Alpha", 20.0),
        ]
        obs_order_2 = [
            _obs("obs-2", "Alpha", 20.0),
            _obs("obs-1", "Zeta", 10.0),
        ]
        ctx1 = _context(obs_order_1, _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        ctx2 = _context(obs_order_2, _rule_set(method="ABSOLUTE", absolute_threshold=1.0))

        r1 = worker.evaluate(ctx1)
        r2 = worker.evaluate(ctx2)

        assert isinstance(r1, DiscrepancyDetectedResult)
        assert isinstance(r2, DiscrepancyDetectedResult)
        assert r1.pair_results[0].pair_id == r2.pair_results[0].pair_id
        assert r1.pair_results[0].source_a == r2.pair_results[0].source_a
        assert r1.pair_results[0].source_b == r2.pair_results[0].source_b


# ===================================================================
# 3. Difference Calculations — Contract §7.1, §7.2
# ===================================================================

class TestDifferenceCalculations:
    """§7.1, §7.2: Exact arithmetic on absolute and percentage differences."""

    def test_absolute_difference_correctness(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.1: absolute_difference = |price_a - price_b|."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 17.5),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.absolute_difference == 7.5

    def test_percentage_difference_uses_lesser_price(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.2: percentage_difference = (abs_diff / min(price_a, price_b)) * 100."""
        # prices: 10.0 and 15.0
        # abs_diff = 5.0, lesser = 10.0
        # pct_diff = (5.0 / 10.0) * 100 = 50.0
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.absolute_difference == 5.0
        assert pair.percentage_difference == 50.0

    def test_percentage_difference_asymmetry(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.2, §15: Denominator must be the LESSER price, not the greater."""
        # prices: 100.0 and 110.0
        # abs_diff = 10.0, lesser = 100.0
        # pct_diff = (10.0 / 100.0) * 100 = 10.0 (NOT 10/110 * 100 ≈ 9.09)
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 110.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.percentage_difference == 10.0

    def test_directionality_fields(self, worker: DiscrepancyWorker) -> None:
        """§7.4: lower_price_source and higher_price_source are correct."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.lower_price_source == "SourceA"
        assert pair.higher_price_source == "SourceB"

    def test_directionality_reversed(self, worker: DiscrepancyWorker) -> None:
        """§7.4: When source_a has the higher price, directionality reflects that."""
        # SourceA (lexicographically lesser) has the higher price
        ctx = _context([
            _obs("obs-1", "SourceA", 30.0),
            _obs("obs-2", "SourceB", 10.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.lower_price_source == "SourceB"
        assert pair.higher_price_source == "SourceA"


# ===================================================================
# 4. Threshold Logic — Contract §7.3
# ===================================================================

class TestThresholdLogic:
    """§7.3: ABSOLUTE, PERCENTAGE, and BOTH threshold methods."""

    # --- ABSOLUTE ---

    def test_absolute_above_threshold(self, worker: DiscrepancyWorker) -> None:
        """§7.3 ABSOLUTE: abs_diff >= threshold → DISCREPANCY_DETECTED."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].threshold_met is True

    def test_absolute_below_threshold(self, worker: DiscrepancyWorker) -> None:
        """§7.3 ABSOLUTE: abs_diff < threshold → NO_DISCREPANCY."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 12.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.pair_results[0].threshold_met is False

    def test_absolute_exactly_at_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.7: abs_diff == threshold → meets threshold (>= semantics)."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.absolute_difference == 5.0
        assert pair.threshold_met is True

    # --- PERCENTAGE ---

    def test_percentage_above_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.3 PERCENTAGE: pct_diff >= threshold → DISCREPANCY_DETECTED."""
        # prices: 10.0 and 15.0 → pct_diff = 50.0
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=25.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].threshold_met is True

    def test_percentage_below_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.3 PERCENTAGE: pct_diff < threshold → NO_DISCREPANCY."""
        # prices: 10.0 and 11.0 → pct_diff = 10.0
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 11.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=25.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.pair_results[0].threshold_met is False

    def test_percentage_exactly_at_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.7: pct_diff == threshold → meets threshold (>= semantics)."""
        # prices: 100.0 and 125.0 → abs_diff = 25.0, pct_diff = 25.0
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 125.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=25.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.percentage_difference == 25.0
        assert pair.threshold_met is True

    # --- BOTH ---

    def test_both_both_met(self, worker: DiscrepancyWorker) -> None:
        """§7.3 BOTH: both thresholds met → DISCREPANCY_DETECTED."""
        # prices: 100.0 and 200.0 → abs_diff = 100.0, pct_diff = 100.0
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 200.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=50.0,
            percentage_threshold=50.0,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].threshold_met is True

    def test_both_absolute_met_percentage_not(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.3 BOTH: absolute met, percentage not → NO_DISCREPANCY."""
        # prices: 100.0 and 110.0 → abs_diff = 10.0, pct_diff = 10.0
        # absolute_threshold = 5.0 (met), percentage_threshold = 20.0 (not met)
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 110.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=5.0,
            percentage_threshold=20.0,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.BELOW_PERCENTAGE_THRESHOLD.value in pair.skip_reason

    def test_both_percentage_met_absolute_not(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.3 BOTH: percentage met, absolute not → NO_DISCREPANCY."""
        # prices: 10.0 and 15.0 → abs_diff = 5.0, pct_diff = 50.0
        # absolute_threshold = 10.0 (not met), percentage_threshold = 25.0 (met)
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=10.0,
            percentage_threshold=25.0,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.BELOW_ABSOLUTE_THRESHOLD.value in pair.skip_reason

    def test_both_neither_met(self, worker: DiscrepancyWorker) -> None:
        """§7.3 BOTH: neither met → NO_DISCREPANCY."""
        # prices: 100.0 and 101.0 → abs_diff = 1.0, pct_diff = 1.0
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 101.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=5.0,
            percentage_threshold=5.0,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.pair_results[0].threshold_met is False

    def test_absolute_threshold_recorded_only_when_applicable(
        self, worker: DiscrepancyWorker
    ) -> None:
        """Threshold used fields reflect the method. PERCENTAGE → no absolute_threshold_used."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=100.0))
        result = worker.evaluate(ctx)

        pair = result.pair_results[0]
        assert pair.absolute_threshold_used is None
        assert pair.percentage_threshold_used == 100.0

    def test_percentage_threshold_recorded_only_when_applicable(
        self, worker: DiscrepancyWorker
    ) -> None:
        """ABSOLUTE → no percentage_threshold_used."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 15.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        pair = result.pair_results[0]
        assert pair.absolute_threshold_used == 1.0
        assert pair.percentage_threshold_used is None


# ===================================================================
# 5. Noise Filters — Contract §7.5
# ===================================================================

class TestNoiseFilters:
    """§7.5: Seven noise filter rules applied in fixed order."""

    def test_filter_5_same_source(self, worker: DiscrepancyWorker) -> None:
        """§7.5.5: Same source → skip (pre-computation filter)."""
        # Need at least 2 distinct sources to pass preconditions,
        # but include a same-source pair via 3 observations.
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceA", 20.0),
            _obs("obs-3", "SourceB", 30.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        # Find the same-source pair
        same_source_pairs = [
            pr for pr in result.pair_results
            if pr.skip_reason and NoiseFilter.SAME_SOURCE.value in pr.skip_reason
        ]
        assert len(same_source_pairs) == 1
        assert same_source_pairs[0].threshold_met is False
        assert same_source_pairs[0].pair_result == DiscrepancyResultType.NO_DISCREPANCY.value

    def test_filter_1_zero_difference(self, worker: DiscrepancyWorker) -> None:
        """§7.5.1: Equal prices → zero difference → skip (post-computation filter)."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 10.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert pair.absolute_difference == 0.0
        assert NoiseFilter.ZERO_DIFFERENCE.value in pair.skip_reason

    def test_filter_2_below_absolute_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.2: abs_diff < absolute_threshold → skip."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 12.0),  # abs_diff = 2.0
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.BELOW_ABSOLUTE_THRESHOLD.value in pair.skip_reason

    def test_filter_3_below_percentage_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.3: pct_diff < percentage_threshold → skip."""
        # prices: 100.0 and 105.0 → pct_diff = 5.0
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 105.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=10.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.BELOW_PERCENTAGE_THRESHOLD.value in pair.skip_reason

    def test_filter_4_price_not_positive_zero(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.4, §9.4: Price of zero → skip (guards against division by zero).

        Note: precondition §5.3 rejects zero/negative prices at the context level.
        This filter defends at the pair level, but since preconditions are checked
        first, we test that the precondition catches it.
        """
        ctx = _context([
            _obs("obs-1", "SourceA", 0.0),
            _obs("obs-2", "SourceB", 10.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        # Precondition §5.3 fires before pair evaluation
        assert isinstance(result, ProcessingFailureResult)
        assert "normalized_price" in result.failure_reason

    def test_filter_4_price_not_positive_negative(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.4: Negative price → precondition §5.3 catches it."""
        ctx = _context([
            _obs("obs-1", "SourceA", -5.0),
            _obs("obs-2", "SourceB", 10.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "normalized_price" in result.failure_reason

    def test_filter_6_unrelated_product_context(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.6: Mismatched product_ref → skip."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, product_ref="product-X"),
            _obs("obs-2", "SourceB", 20.0, product_ref="product-Y"),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.UNRELATED_PRODUCT_CONTEXT.value in pair.skip_reason

    def test_filter_6_matching_product_ref_no_skip(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.6: Same product_ref → no filter applied."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, product_ref="product-X"),
            _obs("obs-2", "SourceB", 20.0, product_ref="product-X"),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        pair = result.pair_results[0]
        assert pair.skip_reason is None

    def test_filter_6_product_ref_absent_no_skip(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.6: If product_ref is not present, filter does not fire."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].skip_reason is None

    def test_filter_7_currency_mismatch(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.7: Mismatched currencies → skip."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, currency="USD"),
            _obs("obs-2", "SourceB", 20.0, currency="EUR"),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        pair = result.pair_results[0]
        assert pair.threshold_met is False
        assert NoiseFilter.CURRENCY_MISMATCH.value in pair.skip_reason

    def test_filter_7_matching_currency_no_skip(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.7: Same currency → no filter applied."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, currency="USD"),
            _obs("obs-2", "SourceB", 20.0, currency="USD"),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].skip_reason is None

    def test_filter_7_currency_absent_no_skip(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§7.5.7: If currency is absent on either side, filter does not fire."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, currency="USD"),
            _obs("obs-2", "SourceB", 20.0),  # no currency field
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pair_results[0].skip_reason is None

    def test_skipped_pair_fields_populated(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§8.2: Skipped pairs still carry source and observation IDs."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0, currency="USD"),
            _obs("obs-2", "SourceB", 10.0, currency="EUR"),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        pair = result.pair_results[0]
        assert pair.source_a == "SourceA"
        assert pair.source_b == "SourceB"
        assert pair.observation_id_a == "obs-1"
        assert pair.observation_id_b == "obs-2"
        assert pair.pair_result == DiscrepancyResultType.NO_DISCREPANCY.value


# ===================================================================
# 6. Multi-Pair Evaluation — Contract §6.4
# ===================================================================

class TestMultiPairEvaluation:
    """§6.4: One valid discrepancy triggers overall DISCREPANCY_DETECTED."""

    def test_one_discrepancy_among_multiple_pairs(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§6.4: Three sources, one pair with discrepancy → overall DISCREPANCY_DETECTED."""
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 100.5),  # close to SourceA
            _obs("obs-3", "SourceC", 200.0),  # far from both
        ], _rule_set(method="ABSOLUTE", absolute_threshold=50.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.pairs_evaluated == 3
        # At least one pair crossed the threshold
        assert result.pairs_with_discrepancy >= 1
        # All pairs included in output
        assert len(result.pair_results) == 3

    def test_no_discrepancy_across_all_pairs(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§6.4: All pairs below threshold → overall NO_DISCREPANCY."""
        ctx = _context([
            _obs("obs-1", "SourceA", 100.0),
            _obs("obs-2", "SourceB", 100.5),
            _obs("obs-3", "SourceC", 101.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.pairs_evaluated == 3
        assert all(not pr.threshold_met for pr in result.pair_results)

    def test_all_pairs_skipped_is_no_discrepancy(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§9.3: All pairs excluded by noise filters → NO_DISCREPANCY (not failure)."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 10.0),  # zero difference
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, NoDiscrepancyResult)
        assert result.pairs_skipped == 1

    def test_pair_results_include_all_pairs(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§6.4: All pair results included regardless of overall classification."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 10.0),   # zero diff → skipped
            _obs("obs-3", "SourceC", 100.0),   # discrepancy with A and B
        ], _rule_set(method="ABSOLUTE", absolute_threshold=5.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert len(result.pair_results) == 3  # A::B, A::C, B::C


# ===================================================================
# 7. Determinism — Contract §10
# ===================================================================

class TestDeterminism:
    """§10: Same input → same output. No clock, no randomness."""

    def test_identical_runs_produce_identical_results(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.1, §10.2: Run evaluate twice on the same context → same result."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
            _obs("obs-3", "SourceC", 15.0),
        ], _rule_set(method="BOTH", absolute_threshold=3.0, percentage_threshold=10.0))

        r1 = worker.evaluate(ctx)
        r2 = worker.evaluate(ctx)

        assert type(r1) is type(r2)
        assert isinstance(r1, DiscrepancyDetectedResult)
        assert r1.result == r2.result
        assert r1.pairs_evaluated == r2.pairs_evaluated
        assert r1.pairs_with_discrepancy == r2.pairs_with_discrepancy
        # Same pair results in same order
        for p1, p2 in zip(r1.pair_results, r2.pair_results):
            assert p1.pair_id == p2.pair_id
            assert p1.absolute_difference == p2.absolute_difference
            assert p1.percentage_difference == p2.percentage_difference
            assert p1.threshold_met == p2.threshold_met
            assert p1.skip_reason == p2.skip_reason

    def test_timestamp_passthrough_no_clock(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§10.5, §14.12: Output timestamp == input timestamp exactly."""
        specific_ts = datetime(2024, 1, 1, 0, 0, 0)
        ctx = _context(
            observations=[
                _obs("obs-1", "SourceA", 10.0),
                _obs("obs-2", "SourceB", 20.0),
            ],
            evaluation_reference_timestamp=specific_ts,
        )
        result = worker.evaluate(ctx)

        assert isinstance(result, DiscrepancyDetectedResult)
        assert result.evaluation_reference_timestamp is specific_ts

    def test_separate_worker_instances_same_result(self) -> None:
        """§10: Worker is stateless — different instances, same context → same result."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 25.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=1.0))

        r1 = DiscrepancyWorker().evaluate(ctx)
        r2 = DiscrepancyWorker().evaluate(ctx)

        assert isinstance(r1, DiscrepancyDetectedResult)
        assert isinstance(r2, DiscrepancyDetectedResult)
        assert r1.pair_results[0].pair_id == r2.pair_results[0].pair_id
        assert r1.pair_results[0].absolute_difference == r2.pair_results[0].absolute_difference


# ===================================================================
# 8. Failure Cases — Contract §5, §8.3, §9
# ===================================================================

class TestFailureCases:
    """§5, §8.3, §9: Precondition failures and invalid inputs."""

    # --- Context-level failures ---

    def test_non_dict_context(self, worker: DiscrepancyWorker) -> None:
        """§9.1: Non-dict context → PROCESSING_FAILURE."""
        result = worker.evaluate("not a dict")  # type: ignore[arg-type]

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_stage == "DISCREPANCY_WORKER"
        assert result.retriable is False

    def test_none_context(self, worker: DiscrepancyWorker) -> None:
        """§9.1: None context → PROCESSING_FAILURE."""
        result = worker.evaluate(None)  # type: ignore[arg-type]

        assert isinstance(result, ProcessingFailureResult)
        assert result.retriable is False

    # --- Missing required fields ---

    def test_missing_pipeline_execution_id(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.6: Missing pipeline_execution_id → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        del ctx["pipeline_execution_id"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "pipeline_execution_id" in result.failure_reason

    def test_missing_evaluation_reference_timestamp(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.5: Missing timestamp → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        del ctx["evaluation_reference_timestamp"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "evaluation_reference_timestamp" in result.failure_reason

    def test_timestamp_wrong_type(self, worker: DiscrepancyWorker) -> None:
        """§5.5: Timestamp not a datetime → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        ctx["evaluation_reference_timestamp"] = "2025-01-01"
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "evaluation_reference_timestamp" in result.failure_reason

    def test_missing_product_id(self, worker: DiscrepancyWorker) -> None:
        """§4.1: Missing product_id → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        del ctx["product_id"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "product_id" in result.failure_reason

    def test_missing_product_name(self, worker: DiscrepancyWorker) -> None:
        """§4.1: Missing product_name → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        del ctx["product_name"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "product_name" in result.failure_reason

    # --- Rule set failures ---

    def test_missing_rule_set(self, worker: DiscrepancyWorker) -> None:
        """§9.2, §5.4: Missing discrepancy_rule_set → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        del ctx["discrepancy_rule_set"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "discrepancy_rule_set" in result.failure_reason
        assert result.retriable is False

    def test_null_rule_set(self, worker: DiscrepancyWorker) -> None:
        """§9.2: Null rule set → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        ctx["discrepancy_rule_set"] = None
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert result.retriable is False

    def test_empty_rule_set(self, worker: DiscrepancyWorker) -> None:
        """§9.2: Empty rule set → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        ctx["discrepancy_rule_set"] = {}
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    def test_invalid_threshold_method(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: Invalid threshold_method → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="INVALID_METHOD", absolute_threshold=1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "threshold_method" in result.failure_reason

    def test_absolute_method_missing_absolute_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: ABSOLUTE method but no absolute_threshold → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=None))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "absolute_threshold" in result.failure_reason

    def test_percentage_method_missing_percentage_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: PERCENTAGE method but no percentage_threshold → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="PERCENTAGE", percentage_threshold=None))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "percentage_threshold" in result.failure_reason

    def test_both_method_missing_absolute_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: BOTH method but no absolute_threshold → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=None,
            percentage_threshold=10.0,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "absolute_threshold" in result.failure_reason

    def test_both_method_missing_percentage_threshold(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: BOTH method but no percentage_threshold → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(
            method="BOTH",
            absolute_threshold=5.0,
            percentage_threshold=None,
        ))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "percentage_threshold" in result.failure_reason

    def test_threshold_value_zero_rejected(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: Threshold must be > 0."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=0.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "absolute_threshold" in result.failure_reason

    def test_threshold_value_negative_rejected(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: Negative threshold → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], _rule_set(method="ABSOLUTE", absolute_threshold=-1.0))
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    def test_boolean_threshold_rejected(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: Boolean is not numeric for thresholds."""
        rs = {"rule_id": FIXED_RULE_ID, "threshold_method": "ABSOLUTE", "absolute_threshold": True}
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], rs)
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    # --- Observation-level failures ---

    def test_fewer_than_two_observations(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.1: Fewer than 2 observations → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
        ])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "two observations" in result.failure_reason.lower() or "two" in result.failure_reason

    def test_two_observations_same_source(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.1: Two observations but same source → PROCESSING_FAILURE."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceA", 20.0),
        ])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "distinct" in result.failure_reason.lower()

    def test_observations_not_a_list(self, worker: DiscrepancyWorker) -> None:
        """§5.1: observations not a list → PROCESSING_FAILURE."""
        ctx = _context([])
        ctx["observations"] = "not a list"
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    def test_observation_missing_source(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§4.2: Observation missing 'source' → PROCESSING_FAILURE."""
        obs = _obs("obs-1", "SourceA", 10.0)
        del obs["source"]
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "source" in result.failure_reason

    def test_observation_missing_observation_id(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§4.2: Observation missing 'observation_id' → PROCESSING_FAILURE."""
        obs = _obs("obs-1", "SourceA", 10.0)
        del obs["observation_id"]
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "observation_id" in result.failure_reason

    def test_observation_missing_listing_ref(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§4.2: Observation missing 'listing_ref' → PROCESSING_FAILURE."""
        obs = _obs("obs-1", "SourceA", 10.0)
        del obs["listing_ref"]
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "listing_ref" in result.failure_reason

    def test_observation_missing_observed_at(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§4.2: Observation missing 'observed_at' → PROCESSING_FAILURE."""
        obs = _obs("obs-1", "SourceA", 10.0)
        del obs["observed_at"]
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "observed_at" in result.failure_reason

    def test_observation_missing_normalized_price(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.3: Observation missing normalized_price → PROCESSING_FAILURE."""
        obs = _obs("obs-1", "SourceA", 10.0)
        del obs["normalized_price"]
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "normalized_price" in result.failure_reason

    def test_observation_boolean_price_rejected(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.3: Boolean is not numeric for prices."""
        obs = _obs("obs-1", "SourceA", 10.0)
        obs["normalized_price"] = True
        ctx = _context([obs, _obs("obs-2", "SourceB", 20.0)])
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    def test_observation_non_dict_rejected(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§4.2: Non-dict observation → PROCESSING_FAILURE."""
        ctx = _context([])
        ctx["observations"] = ["not-a-dict", _obs("obs-2", "SourceB", 20.0)]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)

    # --- Processing failure fields ---

    def test_processing_failure_populates_available_fields(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§8.3: PROCESSING_FAILURE carries as much context as extractable."""
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ])
        ctx["product_name"] = ""  # trigger precondition failure
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.evaluation_reference_timestamp == FIXED_TIMESTAMP

    def test_processing_failure_with_minimal_context(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§8.3: product_id is None when not extractable."""
        result = worker.evaluate({})  # bare dict, nothing extractable

        assert isinstance(result, ProcessingFailureResult)
        assert result.product_id is None

    def test_missing_rule_id_in_rule_set(
        self, worker: DiscrepancyWorker
    ) -> None:
        """§5.4: rule_id missing from rule set → PROCESSING_FAILURE."""
        rs = {"threshold_method": "ABSOLUTE", "absolute_threshold": 1.0}
        ctx = _context([
            _obs("obs-1", "SourceA", 10.0),
            _obs("obs-2", "SourceB", 20.0),
        ], rs)
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert "rule_id" in result.failure_reason
