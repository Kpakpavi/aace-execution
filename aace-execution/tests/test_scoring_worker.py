"""
Unit tests for the Scoring Worker.

Mapped to: Contracts/SCORING_WORKER_CONTRACT.md

Coverage mapping:
    §3, §8         — All three result types (SCORED_OPPORTUNITY, NO_SCORE, PROCESSING_FAILURE)
    §7.1, §7.2     — Precomputed absolute/percentage differences consumed as-is
    §7.3           — Weighted-sum formula, weight-total validation, clamping
    §7.4           — Normalization determinism, bounded outputs, no invention
    §7.2 freshness — Explicit reference timestamp (no system clock)
    §5, §8.3, §9   — Preconditions and failure classifiers
    §10            — Determinism: same input → same output, stable score_result_id
    §8.1           — Output structure (all required fields, full factor breakdown)
    §11.2          — score_result_id deterministic from pipeline_execution_id + pair_id
"""

from __future__ import annotations

import pytest # type: ignore

from src.aace_execution.workers.scoring_worker import (
    FactorApplied,
    FactorType,
    FailureReason,
    FailureStage,
    NoScoreResult,
    ProcessingFailureResult,
    ScoredOpportunityResult,
    ScoringResultType,
    ScoringWorker,
)


# ---------------------------------------------------------------------------
# Fixed reference values — no system clock, no randomness
# ---------------------------------------------------------------------------

FIXED_OBS_TS_A = "2025-06-15T10:00:00+00:00"
FIXED_OBS_TS_B = "2025-06-15T11:00:00+00:00"
FIXED_FRESHNESS_REF_TS = "2025-06-15T12:00:00+00:00"  # 1h after most recent
FIXED_SCORING_TS = "2025-06-15T12:00:05+00:00"

FIXED_PIPELINE_ID = "pipe-test-001"
FIXED_PAIR_ID = "SourceA::SourceB"
FIXED_PRODUCT_ID = "prod-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _factor(
    factor_name: str,
    factor_type: str,
    weight: float | int,
) -> dict:
    """Build a factor configuration entry."""
    return {
        "factor_name": factor_name,
        "factor_type": factor_type,
        "weight": weight,
    }


def _input(
    *,
    discrepancy_result: str = "DISCREPANCY_DETECTED",
    price_a: float = 10.0,
    price_b: float = 20.0,
    absolute_difference: float = 10.0,
    percentage_difference: float = 100.0,
    threshold_method: str = "ABSOLUTE",
    source_a: str = "SourceA",
    source_b: str = "SourceB",
    lower_price_source: str = "SourceA",
    higher_price_source: str = "SourceB",
    observation_timestamp_a: str | None = FIXED_OBS_TS_A,
    observation_timestamp_b: str | None = FIXED_OBS_TS_B,
    freshness_reference_timestamp: str | None = FIXED_FRESHNESS_REF_TS,
    scoring_timestamp: str | None = FIXED_SCORING_TS,
    pipeline_execution_id: str | None = FIXED_PIPELINE_ID,
    pair_id: str | None = FIXED_PAIR_ID,
    product_id: str | None = FIXED_PRODUCT_ID,
    scoring_factors: list[dict] | None = None,
    score_range: dict | None = None,
    normalization_method: str | None = None,
    tie_break_order: list[str] | None = None,
) -> dict:
    """Build a full scoring input dict with optional overrides."""
    if scoring_factors is None:
        scoring_factors = [
            _factor("price_difference", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
        ]
    if score_range is None:
        score_range = {"min": 0.0, "max": 100.0}
    if tie_break_order is None:
        tie_break_order = [
            "higher_absolute_difference",
            "more_recent_observation",
            "lower_product_id",
        ]
    return {
        "pipeline_execution_id": pipeline_execution_id,
        "pair_id": pair_id,
        "product_id": product_id,
        "discrepancy_result": discrepancy_result,
        "source_a": source_a,
        "source_b": source_b,
        "price_a": price_a,
        "price_b": price_b,
        "absolute_difference": absolute_difference,
        "percentage_difference": percentage_difference,
        "threshold_method": threshold_method,
        "lower_price_source": lower_price_source,
        "higher_price_source": higher_price_source,
        "observation_timestamp_a": observation_timestamp_a,
        "observation_timestamp_b": observation_timestamp_b,
        "freshness_reference_timestamp": freshness_reference_timestamp,
        "scoring_timestamp": scoring_timestamp,
        "scoring_factors": scoring_factors,
        "score_range": score_range,
        "normalization_method": normalization_method,
        "tie_break_order": tie_break_order,
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def worker() -> ScoringWorker:
    return ScoringWorker()


# ===================================================================
# 1. Result Types — Contract §8
# ===================================================================

class TestResultTypes:
    """§8: Exactly one of SCORED_OPPORTUNITY, NO_SCORE, PROCESSING_FAILURE."""

    def test_scored_opportunity(self, worker: ScoringWorker) -> None:
        """§8.1: Valid input → SCORED_OPPORTUNITY with all required fields."""
        result = worker.evaluate(_input())

        assert isinstance(result, ScoredOpportunityResult)
        assert result.result == ScoringResultType.SCORED_OPPORTUNITY.value
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.pair_id == FIXED_PAIR_ID
        assert result.product_id == FIXED_PRODUCT_ID

    def test_processing_failure_on_wrong_discrepancy_result(
        self, worker: ScoringWorker
    ) -> None:
        """§5.1, §9.1: discrepancy_result ≠ DISCREPANCY_DETECTED → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(discrepancy_result="NO_DISCREPANCY"))

        assert isinstance(result, ProcessingFailureResult)
        assert result.result == ScoringResultType.PROCESSING_FAILURE.value
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value

    def test_no_score_type_is_defined(self) -> None:
        """§8.2: NO_SCORE result type must be defined and constructible.

        Contract §8.2 restricts NO_SCORE to explicit spec-defined
        ineligibility conditions. The contract as written lists no such
        positive condition — so no code path emits it, but the type must
        exist and be usable once the spec defines such a condition.
        """
        no_score = NoScoreResult(
            result=ScoringResultType.NO_SCORE.value,
            pipeline_execution_id=FIXED_PIPELINE_ID,
            pair_id=FIXED_PAIR_ID,
            product_id=FIXED_PRODUCT_ID,
            ineligibility_reason="SPEC_DEFINED_INELIGIBILITY",
            discrepancy_result_received="DISCREPANCY_DETECTED",
        )
        assert no_score.result == "NO_SCORE"
        assert no_score.ineligibility_reason == "SPEC_DEFINED_INELIGIBILITY"


# ===================================================================
# 2. Score Calculation — Contract §7.1, §7.2, §7.3
# ===================================================================

class TestScoreCalculation:
    """§7.3: raw_score = sum(weight_i * normalized_factor_value_i)."""

    def test_single_factor_absolute_difference(
        self, worker: ScoringWorker
    ) -> None:
        """§7.1: absolute_difference used as-is, weight=1.0 → score = raw value (clamped)."""
        # abs_diff=10.0, weight=1.0, no normalization → raw_score=10.0
        result = worker.evaluate(_input(
            absolute_difference=10.0,
            scoring_factors=[
                _factor("price_diff", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score == 10.0
        assert result.score_clamped is False

    def test_single_factor_percentage_difference(
        self, worker: ScoringWorker
    ) -> None:
        """§7.2: percentage_difference used as-is."""
        result = worker.evaluate(_input(
            percentage_difference=75.0,
            scoring_factors=[
                _factor("pct_diff", FactorType.PERCENTAGE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score == 75.0

    def test_weighted_two_factors_sum_to_one(
        self, worker: ScoringWorker
    ) -> None:
        """§7.3: Multiple factors — weighted sum is the score."""
        # abs_diff=40.0 (weight 0.6) + pct_diff=50.0 (weight 0.4)
        # raw_score = 0.6*40 + 0.4*50 = 24 + 20 = 44.0
        result = worker.evaluate(_input(
            absolute_difference=40.0,
            percentage_difference=50.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 0.6),
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 0.4),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score == pytest.approx(44.0)
        assert result.weights_sum == pytest.approx(1.0)
        assert len(result.factors_applied) == 2

    def test_factor_contributions_sum_to_score(
        self, worker: ScoringWorker
    ) -> None:
        """§14.11: sum of weighted_contribution == final score (within precision)."""
        result = worker.evaluate(_input(
            absolute_difference=30.0,
            percentage_difference=60.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 0.5),
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 0.5),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        contribution_sum = sum(
            f.weighted_contribution for f in result.factors_applied
        )
        assert result.score == pytest.approx(contribution_sum)

    def test_higher_difference_produces_higher_score(
        self, worker: ScoringWorker
    ) -> None:
        """§14.3: Higher discrepancy → higher score, all else equal."""
        small = worker.evaluate(_input(
            absolute_difference=10.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
        ))
        large = worker.evaluate(_input(
            absolute_difference=50.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(small, ScoredOpportunityResult)
        assert isinstance(large, ScoredOpportunityResult)
        assert large.score > small.score

    def test_score_clamped_to_max(self, worker: ScoringWorker) -> None:
        """§7.3: Score above range clamped to max; score_clamped=True."""
        # abs_diff=500 with weight=1.0, no normalization → raw=500
        # score_range max=100 → clamped to 100
        result = worker.evaluate(_input(
            absolute_difference=500.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
            score_range={"min": 0.0, "max": 100.0},
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score == 100.0
        assert result.score_clamped is True

    def test_score_clamped_to_min(self, worker: ScoringWorker) -> None:
        """§7.3: Score below range clamped to min; score_clamped=True."""
        # Negative weight would make contribution negative
        # weight=1.0, abs_diff=-5... but abs_diff is non-negative in practice.
        # Instead, use score_range starting above 0.
        result = worker.evaluate(_input(
            absolute_difference=5.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
            score_range={"min": 10.0, "max": 100.0},
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score == 10.0
        assert result.score_clamped is True


# ===================================================================
# 3. Weight Validation — Contract §7.3, §9.2
# ===================================================================

class TestWeightValidation:
    """§7.3: Weights sum to 1.0 OR integer proportional total."""

    def test_fractional_weights_sum_to_one(
        self, worker: ScoringWorker
    ) -> None:
        """§7.3: Sum exactly 1.0 → valid."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, 0.3),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 0.7),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.weights_sum == pytest.approx(1.0)

    def test_integer_weights_positive_total(
        self, worker: ScoringWorker
    ) -> None:
        """§7.3: Integer weights with positive integer total → valid."""
        # Integer weights: 3 + 7 = 10
        # raw_score = 3*10 + 7*20 = 30 + 140 = 170
        result = worker.evaluate(_input(
            absolute_difference=10.0,
            percentage_difference=20.0,
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, 3),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 7),
            ],
            score_range={"min": 0.0, "max": 1000.0},
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.weights_sum == 10
        assert result.score == pytest.approx(170.0)

    def test_weights_do_not_sum_to_one_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§7.3, §9.2: Fractional weights not summing to 1.0 → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, 0.3),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 0.5),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_weights_above_one_rejected(self, worker: ScoringWorker) -> None:
        """§7.3: Fractional weights above 1.0 → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, 0.6),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 0.6),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_zero_total_weights_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§7.3: Weights summing to 0 (all zero) → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, 0),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 0),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_missing_weight_rejected(self, worker: ScoringWorker) -> None:
        """§5.3: Factor without weight → PROCESSING_FAILURE."""
        bad_factor = {
            "factor_name": "abs",
            "factor_type": FactorType.ABSOLUTE_DIFFERENCE.value,
        }
        result = worker.evaluate(_input(scoring_factors=[bad_factor]))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value
        assert "weight" in result.error_context

    def test_negative_weight_rejected(self, worker: ScoringWorker) -> None:
        """§5.3: Negative weight → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, -0.5),
                _factor("b", FactorType.PERCENTAGE_DIFFERENCE.value, 1.5),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_boolean_weight_rejected(self, worker: ScoringWorker) -> None:
        """§5.3: Boolean is not numeric for weights."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("a", FactorType.ABSOLUTE_DIFFERENCE.value, True),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value


# ===================================================================
# 4. Factor Handling — Contract §7, §10.8, §9.3
# ===================================================================

class TestFactorHandling:
    """§7, §10.8: Only configured factor types applied. Unknown → failure."""

    def test_absolute_difference_factor_type(
        self, worker: ScoringWorker
    ) -> None:
        """§7.1: absolute_difference factor type supported."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.factors_applied[0].factor_type == "absolute_difference"

    def test_percentage_difference_factor_type(
        self, worker: ScoringWorker
    ) -> None:
        """§7.2: percentage_difference factor type supported."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.factors_applied[0].factor_type == "percentage_difference"

    def test_freshness_decay_factor_type(
        self, worker: ScoringWorker
    ) -> None:
        """§7.2: freshness_decay factor type supported."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("fresh", FactorType.FRESHNESS_DECAY.value, 1.0),
            ],
            normalization_method="LINEAR_BOUNDED",
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.factors_applied[0].factor_type == "freshness_decay"

    def test_unknown_factor_type_fails(
        self, worker: ScoringWorker
    ) -> None:
        """§10.8: Unknown factor_type → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("mystery", "unknown_factor_type", 1.0),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value
        assert "unknown_factor_type" in result.error_context

    def test_missing_factor_type_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.3: Factor without factor_type → PROCESSING_FAILURE."""
        bad_factor = {"factor_name": "abs", "weight": 1.0}
        result = worker.evaluate(_input(scoring_factors=[bad_factor]))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_missing_factor_name_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.3: Factor without factor_name → PROCESSING_FAILURE."""
        bad_factor = {
            "factor_type": FactorType.ABSOLUTE_DIFFERENCE.value,
            "weight": 1.0,
        }
        result = worker.evaluate(_input(scoring_factors=[bad_factor]))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_duplicate_factor_names_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.3: Duplicate factor_name → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            scoring_factors=[
                _factor("dup", FactorType.ABSOLUTE_DIFFERENCE.value, 0.5),
                _factor("dup", FactorType.PERCENTAGE_DIFFERENCE.value, 0.5),
            ],
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_empty_scoring_factors_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.2, §9.2: Empty scoring_factors → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(scoring_factors=[]))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_invalid_factor_value_nonfinite(
        self, worker: ScoringWorker
    ) -> None:
        """§9.3: Non-finite input difference value → INVALID_DISCREPANCY_INPUT."""
        result = worker.evaluate(_input(
            absolute_difference=float("inf"),
        ))

        assert isinstance(result, ProcessingFailureResult)
        # Non-finite diff caught in preconditions (§9.1 INVALID_DISCREPANCY_INPUT)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_invalid_price_rejected(self, worker: ScoringWorker) -> None:
        """§5.5, §9.1: Zero price → PRECONDITION_VIOLATION."""
        result = worker.evaluate(_input(price_a=0.0))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value

    def test_negative_price_rejected(self, worker: ScoringWorker) -> None:
        """§5.5: Negative price → PRECONDITION_VIOLATION."""
        result = worker.evaluate(_input(price_b=-1.0))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value


# ===================================================================
# 5. Normalization Handling — Contract §7.4
# ===================================================================

class TestNormalization:
    """§7.4: Deterministic, bounded, documented; no invention."""

    def test_no_normalization_uses_raw(
        self, worker: ScoringWorker
    ) -> None:
        """§7.4: No normalization_method → raw value used as-is."""
        result = worker.evaluate(_input(
            absolute_difference=42.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
            normalization_method=None,
        ))

        assert isinstance(result, ScoredOpportunityResult)
        f = result.factors_applied[0]
        assert f.raw_value == 42.0
        assert f.normalized_value == 42.0
        assert result.normalization_method is None

    def test_linear_bounded_clamps_to_range(
        self, worker: ScoringWorker
    ) -> None:
        """§7.4: LINEAR_BOUNDED produces values within score_range."""
        # abs_diff=500 with LINEAR_BOUNDED clamps each factor's normalized
        # value to score_max=100.
        result = worker.evaluate(_input(
            absolute_difference=500.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
            normalization_method="LINEAR_BOUNDED",
            score_range={"min": 0.0, "max": 100.0},
        ))

        assert isinstance(result, ScoredOpportunityResult)
        f = result.factors_applied[0]
        assert f.raw_value == 500.0
        assert f.normalized_value == 100.0  # clamped into score_range
        assert f.normalized_value <= 100.0
        assert f.normalized_value >= 0.0
        assert result.normalization_method == "LINEAR_BOUNDED"

    def test_linear_bounded_freshness_inverts_age(
        self, worker: ScoringWorker
    ) -> None:
        """§7.2, §7.4: Fresher observation → higher freshness factor."""
        # Older observation (age=3600s) vs fresher (age=60s)
        older = worker.evaluate(_input(
            observation_timestamp_a="2025-06-15T11:00:00+00:00",
            observation_timestamp_b="2025-06-15T11:00:00+00:00",
            freshness_reference_timestamp="2025-06-15T12:00:00+00:00",  # 1h later
            scoring_factors=[
                _factor("fresh", FactorType.FRESHNESS_DECAY.value, 1.0),
            ],
            normalization_method="LINEAR_BOUNDED",
        ))
        fresher = worker.evaluate(_input(
            observation_timestamp_a="2025-06-15T11:59:00+00:00",
            observation_timestamp_b="2025-06-15T11:59:00+00:00",
            freshness_reference_timestamp="2025-06-15T12:00:00+00:00",  # 60s later
            scoring_factors=[
                _factor("fresh", FactorType.FRESHNESS_DECAY.value, 1.0),
            ],
            normalization_method="LINEAR_BOUNDED",
        ))

        assert isinstance(older, ScoredOpportunityResult)
        assert isinstance(fresher, ScoredOpportunityResult)
        assert fresher.factors_applied[0].normalized_value > older.factors_applied[0].normalized_value
        # §14.4: fresher → higher factor contribution
        assert fresher.score > older.score

    def test_unknown_normalization_method_fails(
        self, worker: ScoringWorker
    ) -> None:
        """§7.4, §10.7: Unknown normalization method → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            normalization_method="MYSTERY_METHOD",
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value
        assert "MYSTERY_METHOD" in result.error_context

    def test_normalization_method_recorded_in_output(
        self, worker: ScoringWorker
    ) -> None:
        """§7.4: Normalization method is documented in the output."""
        result = worker.evaluate(_input(
            normalization_method="LINEAR_BOUNDED",
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.normalization_method == "LINEAR_BOUNDED"


# ===================================================================
# 6. Freshness Handling — Contract §7.2, §10.4
# ===================================================================

class TestFreshness:
    """§7.2, §10.4: Freshness uses explicit reference timestamp, no clock."""

    def test_freshness_uses_explicit_reference(
        self, worker: ScoringWorker
    ) -> None:
        """§7.2: Age computed from passed-in reference timestamp."""
        # Most recent obs = 11:00:00, reference = 12:00:00 → age = 3600s
        result = worker.evaluate(_input(
            observation_timestamp_a="2025-06-15T10:00:00+00:00",
            observation_timestamp_b="2025-06-15T11:00:00+00:00",
            freshness_reference_timestamp="2025-06-15T12:00:00+00:00",
            scoring_factors=[
                _factor("fresh", FactorType.FRESHNESS_DECAY.value, 1.0),
            ],
            normalization_method="LINEAR_BOUNDED",
        ))

        assert isinstance(result, ScoredOpportunityResult)
        f = result.factors_applied[0]
        assert f.raw_value == 3600.0  # exact age in seconds

    def test_reference_earlier_than_observation_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.7: freshness_reference_timestamp must be ≥ both obs timestamps."""
        result = worker.evaluate(_input(
            observation_timestamp_a="2025-06-15T12:00:00+00:00",
            observation_timestamp_b="2025-06-15T13:00:00+00:00",
            freshness_reference_timestamp="2025-06-15T11:00:00+00:00",  # earlier
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value

    def test_missing_freshness_reference_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.7: Missing freshness_reference_timestamp → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            freshness_reference_timestamp=None,
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value

    def test_invalid_iso8601_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§5.6: Malformed ISO 8601 → PROCESSING_FAILURE."""
        result = worker.evaluate(_input(
            observation_timestamp_a="not-a-timestamp",
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_z_suffix_iso8601_accepted(
        self, worker: ScoringWorker
    ) -> None:
        """§5.6: 'Z' suffix is a valid ISO 8601 form."""
        result = worker.evaluate(_input(
            observation_timestamp_a="2025-06-15T10:00:00Z",
            observation_timestamp_b="2025-06-15T11:00:00Z",
            freshness_reference_timestamp="2025-06-15T12:00:00Z",
            scoring_timestamp="2025-06-15T12:00:05Z",
        ))

        assert isinstance(result, ScoredOpportunityResult)

    def test_missing_scoring_timestamp_rejected(
        self, worker: ScoringWorker
    ) -> None:
        """§10.10: scoring_timestamp must be passed in."""
        result = worker.evaluate(_input(scoring_timestamp=None))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value
        assert "scoring_timestamp" in result.error_context

    def test_freshness_timestamps_echoed_in_output(
        self, worker: ScoringWorker
    ) -> None:
        """§8.1: freshness_reference_timestamp and scoring_timestamp in output."""
        result = worker.evaluate(_input())

        assert isinstance(result, ScoredOpportunityResult)
        assert result.freshness_reference_timestamp == FIXED_FRESHNESS_REF_TS
        assert result.scoring_timestamp == FIXED_SCORING_TS


# ===================================================================
# 7. Determinism — Contract §10, §11
# ===================================================================

class TestDeterminism:
    """§10: Same input → same output. Stable score_result_id."""

    def test_same_input_same_output(self, worker: ScoringWorker) -> None:
        """§10.1, §14.2: Two runs produce identical results."""
        ctx = _input(
            absolute_difference=30.0,
            percentage_difference=60.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 0.4),
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 0.6),
            ],
        )

        r1 = worker.evaluate(ctx)
        r2 = worker.evaluate(ctx)

        assert isinstance(r1, ScoredOpportunityResult)
        assert isinstance(r2, ScoredOpportunityResult)
        assert r1.score == r2.score
        assert r1.score_result_id == r2.score_result_id
        assert r1.weights_sum == r2.weights_sum
        assert len(r1.factors_applied) == len(r2.factors_applied)
        for f1, f2 in zip(r1.factors_applied, r2.factors_applied):
            assert f1.factor_name == f2.factor_name
            assert f1.raw_value == f2.raw_value
            assert f1.normalized_value == f2.normalized_value
            assert f1.weighted_contribution == f2.weighted_contribution

    def test_score_result_id_deterministic(
        self, worker: ScoringWorker
    ) -> None:
        """§11.2: score_result_id derived from pipeline_execution_id + pair_id."""
        result = worker.evaluate(_input())

        assert isinstance(result, ScoredOpportunityResult)
        assert FIXED_PIPELINE_ID in result.score_result_id
        assert FIXED_PAIR_ID in result.score_result_id

    def test_score_result_id_differs_by_pair_id(
        self, worker: ScoringWorker
    ) -> None:
        """§11.2: Different pair_id → different score_result_id."""
        r1 = worker.evaluate(_input(pair_id="SourceA::SourceB"))
        r2 = worker.evaluate(_input(pair_id="SourceC::SourceD"))

        assert isinstance(r1, ScoredOpportunityResult)
        assert isinstance(r2, ScoredOpportunityResult)
        assert r1.score_result_id != r2.score_result_id

    def test_score_result_id_differs_by_pipeline_id(
        self, worker: ScoringWorker
    ) -> None:
        """§11.2: Different pipeline_execution_id → different score_result_id."""
        r1 = worker.evaluate(_input(pipeline_execution_id="pipe-A"))
        r2 = worker.evaluate(_input(pipeline_execution_id="pipe-B"))

        assert isinstance(r1, ScoredOpportunityResult)
        assert isinstance(r2, ScoredOpportunityResult)
        assert r1.score_result_id != r2.score_result_id

    def test_separate_worker_instances_same_result(self) -> None:
        """§10: Worker is stateless — different instances, same input → same result."""
        ctx = _input()

        r1 = ScoringWorker().evaluate(ctx)
        r2 = ScoringWorker().evaluate(ctx)

        assert isinstance(r1, ScoredOpportunityResult)
        assert isinstance(r2, ScoredOpportunityResult)
        assert r1.score == r2.score
        assert r1.score_result_id == r2.score_result_id

    def test_tie_break_order_carried_forward(
        self, worker: ScoringWorker
    ) -> None:
        """§7.5, §8.1: tie_break_order preserved in output for downstream ranking."""
        custom_order = ["criterion_x", "criterion_y"]
        result = worker.evaluate(_input(tie_break_order=custom_order))

        assert isinstance(result, ScoredOpportunityResult)
        assert list(result.tie_break_order) == custom_order


# ===================================================================
# 8. Output Structure — Contract §8.1, §14.14
# ===================================================================

class TestOutputStructure:
    """§8.1: Required fields; §14.14: reviewer can reconstruct the score."""

    def test_all_required_top_level_fields(
        self, worker: ScoringWorker
    ) -> None:
        """§8.1: Every field in the SCORED_OPPORTUNITY table is populated."""
        result = worker.evaluate(_input())

        assert isinstance(result, ScoredOpportunityResult)
        assert result.result == "SCORED_OPPORTUNITY"
        assert result.pipeline_execution_id
        assert result.score_result_id
        assert result.product_id
        assert result.pair_id
        assert result.discrepancy_reference is not None
        assert result.score is not None
        assert result.score_range is not None
        assert len(result.factors_applied) > 0
        assert result.weights_sum is not None
        # normalization_method may be None when none configured
        assert result.score_clamped in (True, False)
        assert result.tie_break_order is not None
        assert result.freshness_reference_timestamp
        assert result.scoring_timestamp

    def test_discrepancy_reference_echoes_input(
        self, worker: ScoringWorker
    ) -> None:
        """§8.1: discrepancy_reference contains key discrepancy fields."""
        result = worker.evaluate(_input(
            source_a="Src1",
            source_b="Src2",
            price_a=15.0,
            price_b=25.0,
            absolute_difference=10.0,
            percentage_difference=66.67,
            threshold_method="BOTH",
        ))

        assert isinstance(result, ScoredOpportunityResult)
        ref = result.discrepancy_reference
        assert ref["source_a"] == "Src1"
        assert ref["source_b"] == "Src2"
        assert ref["price_a"] == 15.0
        assert ref["price_b"] == 25.0
        assert ref["absolute_difference"] == 10.0
        assert ref["percentage_difference"] == 66.67
        assert ref["threshold_method"] == "BOTH"

    def test_factor_breakdown_has_all_required_fields(
        self, worker: ScoringWorker
    ) -> None:
        """§8.1: Each factors_applied entry: name, type, raw, normalized, weight, contribution."""
        result = worker.evaluate(_input(
            absolute_difference=20.0,
            percentage_difference=40.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 0.3),
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 0.7),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert len(result.factors_applied) == 2
        for f in result.factors_applied:
            assert isinstance(f, FactorApplied)
            assert f.factor_name
            assert f.factor_type
            assert f.raw_value is not None
            assert f.normalized_value is not None
            assert f.weight is not None
            assert f.weighted_contribution is not None

    def test_score_range_echoed_in_output(
        self, worker: ScoringWorker
    ) -> None:
        """§8.1: score_range echoed as {min, max}."""
        result = worker.evaluate(_input(
            score_range={"min": 0.0, "max": 50.0},
            absolute_difference=25.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 1.0),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        assert result.score_range == {"min": 0.0, "max": 50.0}

    def test_explanation_reconstructs_score(
        self, worker: ScoringWorker
    ) -> None:
        """§14.14: factor_applied + weights + formula reconstructs the score."""
        result = worker.evaluate(_input(
            absolute_difference=30.0,
            percentage_difference=50.0,
            scoring_factors=[
                _factor("abs", FactorType.ABSOLUTE_DIFFERENCE.value, 0.4),
                _factor("pct", FactorType.PERCENTAGE_DIFFERENCE.value, 0.6),
            ],
        ))

        assert isinstance(result, ScoredOpportunityResult)
        # Reconstruct from factors_applied alone:
        reconstructed = sum(
            f.weight * f.normalized_value for f in result.factors_applied
        )
        # score may be clamped; within range it must equal reconstructed
        if not result.score_clamped:
            assert result.score == pytest.approx(reconstructed)

    def test_processing_failure_output_fields(
        self, worker: ScoringWorker
    ) -> None:
        """§8.3: PROCESSING_FAILURE carries failure_reason, failure_stage, retriable, error_context."""
        result = worker.evaluate(_input(discrepancy_result="NO_DISCREPANCY"))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value
        assert result.failure_stage == FailureStage.PRECONDITION_CHECK.value
        assert result.retriable is False
        assert len(result.error_context) > 0
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.pair_id == FIXED_PAIR_ID
        assert result.product_id == FIXED_PRODUCT_ID


# ===================================================================
# 9. Additional Precondition Coverage — Contract §5, §9
# ===================================================================

class TestPreconditions:
    """§5: Eight preconditions must be satisfied before scoring."""

    def test_non_dict_input(self, worker: ScoringWorker) -> None:
        """§9.1: Non-dict input → INVALID_DISCREPANCY_INPUT."""
        result = worker.evaluate("not a dict")  # type: ignore[arg-type]

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_none_input(self, worker: ScoringWorker) -> None:
        """§9.1: None input → INVALID_DISCREPANCY_INPUT."""
        result = worker.evaluate(None)  # type: ignore[arg-type]

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_missing_pipeline_execution_id(
        self, worker: ScoringWorker
    ) -> None:
        """§5.8: Missing pipeline_execution_id → PRECONDITION_VIOLATION."""
        result = worker.evaluate(_input(pipeline_execution_id=None))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.PRECONDITION_VIOLATION.value

    def test_missing_pair_id(self, worker: ScoringWorker) -> None:
        """§4: Missing pair_id → INVALID_DISCREPANCY_INPUT."""
        result = worker.evaluate(_input(pair_id=None))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_missing_product_id(self, worker: ScoringWorker) -> None:
        """§4: Missing product_id → INVALID_DISCREPANCY_INPUT."""
        result = worker.evaluate(_input(product_id=None))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_DISCREPANCY_INPUT.value

    def test_invalid_score_range_min_gte_max(
        self, worker: ScoringWorker
    ) -> None:
        """§5.4: score_range.min >= score_range.max → INVALID_SCORING_CONFIGURATION."""
        result = worker.evaluate(_input(
            score_range={"min": 100.0, "max": 100.0},
        ))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_invalid_score_range_missing(
        self, worker: ScoringWorker
    ) -> None:
        """§5.4: Missing score_range → INVALID_SCORING_CONFIGURATION."""
        ctx = _input()
        del ctx["score_range"]
        result = worker.evaluate(ctx)

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == FailureReason.INVALID_SCORING_CONFIGURATION.value

    def test_failure_stage_populated(self, worker: ScoringWorker) -> None:
        """§8.3, §15: PROCESSING_FAILURE must always include failure_stage."""
        result = worker.evaluate(_input(discrepancy_result="PROCESSING_FAILURE"))

        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_stage  # non-empty
        assert result.failure_reason  # non-empty
