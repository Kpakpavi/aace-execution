"""
Scoring Worker — Stage 5 of the AACE Opportunity Pipeline.

Contract: Contracts/SCORING_WORKER_CONTRACT.md

Consumes a valid DISCREPANCY_DETECTED result and produces a single deterministic
opportunity score using only the scoring factors and weights defined in the
loaded configuration.

Determinism guarantees (Contract §10):
    - Same input → same output.
    - No system clock is consulted.
    - No randomness.
    - No external calls.
    - No AI model invocation.
    - No factor, weight, or normalization method is hardcoded here — all come
      from the loaded configuration.

What this worker does NOT do (Contract §13):
    - Detect discrepancies.
    - Evaluate alert eligibility.
    - Persist data.
    - Fetch or enrich data.
    - Redefine weights, thresholds, or normalization rules.
    - Use the system clock.
    - Invoke AI models or probabilistic heuristics.
    - Operate on more than one discrepancy per invocation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result classification — Contract §8
# ---------------------------------------------------------------------------

class ScoringResultType(str, Enum):
    """
    The three and only three result states the worker may produce.
    Contract §8.
    """
    SCORED_OPPORTUNITY  = "SCORED_OPPORTUNITY"
    NO_SCORE            = "NO_SCORE"
    PROCESSING_FAILURE  = "PROCESSING_FAILURE"


# ---------------------------------------------------------------------------
# Failure reason classification — Contract §8.3, §9
# ---------------------------------------------------------------------------

class FailureReason(str, Enum):
    """
    The exhaustive set of failure reason classifiers — Contract §8.3.
    """
    PRECONDITION_VIOLATION        = "PRECONDITION_VIOLATION"
    INVALID_SCORING_CONFIGURATION = "INVALID_SCORING_CONFIGURATION"
    INVALID_FACTOR_VALUE          = "INVALID_FACTOR_VALUE"
    INVALID_DISCREPANCY_INPUT     = "INVALID_DISCREPANCY_INPUT"
    UNEXPECTED_RUNTIME_ERROR      = "UNEXPECTED_RUNTIME_ERROR"


# ---------------------------------------------------------------------------
# Sub-stage identifiers used in PROCESSING_FAILURE outputs — Contract §8.3
# ---------------------------------------------------------------------------

class FailureStage(str, Enum):
    """Sub-stage within this worker where the failure occurred."""
    INPUT_PARSE         = "INPUT_PARSE"
    PRECONDITION_CHECK  = "PRECONDITION_CHECK"
    FACTOR_COMPUTATION  = "FACTOR_COMPUTATION"
    SCORE_ASSEMBLY      = "SCORE_ASSEMBLY"


# ---------------------------------------------------------------------------
# Factor type identifiers — Contract §4 (scoring_factors.factor_type)
#
# These are the computation-method names the configuration refers to. Behavior
# for each is defined by the spec (§7.1, §7.2). No factor may be applied that
# is not explicitly listed in the loaded configuration (§10.8).
# ---------------------------------------------------------------------------

class FactorType(str, Enum):
    """Known factor computation methods — Contract §7."""
    ABSOLUTE_DIFFERENCE   = "absolute_difference"
    PERCENTAGE_DIFFERENCE = "percentage_difference"
    FRESHNESS_DECAY       = "freshness_decay"


# ---------------------------------------------------------------------------
# Per-factor result — Contract §8.1 (factors_applied entry)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FactorApplied:
    """
    Full audit detail for a single applied scoring factor.
    Contract §8.1 table, §10.2 (no hidden heuristics), §14.14 (reconstructable).
    """
    factor_name: str
    factor_type: str
    raw_value: float
    normalized_value: float
    weight: float
    weighted_contribution: float


# ---------------------------------------------------------------------------
# Top-level result dataclasses — Contract §8.1, §8.2, §8.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoredOpportunityResult:
    """Contract §8.1 — successful scoring output."""
    result: str                          # always ScoringResultType.SCORED_OPPORTUNITY
    pipeline_execution_id: str
    score_result_id: str
    product_id: str
    pair_id: str
    discrepancy_reference: dict
    score: float
    score_range: dict                    # {"min": float, "max": float}
    factors_applied: tuple[FactorApplied, ...]
    weights_sum: float
    normalization_method: str | None
    score_clamped: bool
    tie_break_order: tuple[str, ...]
    freshness_reference_timestamp: str
    scoring_timestamp: str


@dataclass(frozen=True)
class NoScoreResult:
    """
    Contract §8.2 — explicit spec-defined ineligibility (not a failure).

    Note: §8.2 restricts NO_SCORE to ineligibility conditions *explicitly
    defined in the spec*. Anything structural (missing rule set, bad
    discrepancy_result value, malformed input) is a PROCESSING_FAILURE
    per §8.2 and §9.
    """
    result: str                          # always ScoringResultType.NO_SCORE
    pipeline_execution_id: str
    pair_id: str
    product_id: str
    ineligibility_reason: str
    discrepancy_result_received: str


@dataclass(frozen=True)
class ProcessingFailureResult:
    """Contract §8.3 — structural, configuration, or runtime failure."""
    result: str                          # always ScoringResultType.PROCESSING_FAILURE
    pipeline_execution_id: str | None
    pair_id: str | None
    product_id: str | None
    failure_reason: str                  # FailureReason.*
    failure_stage: str                   # FailureStage.*
    retriable: bool
    error_context: str


# Union type for return annotations
ScoringResult = (
    ScoredOpportunityResult | NoScoreResult | ProcessingFailureResult
)


# ---------------------------------------------------------------------------
# Internal exceptions — classified failures raised by helpers, caught and
# converted to ProcessingFailureResult by evaluate(). Never leak to callers.
# ---------------------------------------------------------------------------

class _ScoringError(Exception):
    """Base class for classified scoring errors."""

    def __init__(
        self,
        reason: FailureReason,
        stage: FailureStage,
        context: str,
        retriable: bool = False,
    ) -> None:
        super().__init__(context)
        self.reason    = reason
        self.stage     = stage
        self.context   = context
        self.retriable = retriable


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class ScoringWorker:
    """
    Scores a single confirmed DISCREPANCY_DETECTED result deterministically.

    The worker is stateless. Call ``evaluate()`` once per discrepancy.
    The same input always returns the same result (Contract §10.1).

    Usage::

        worker = ScoringWorker()
        result = worker.evaluate(scoring_input)
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, scoring_input: dict[str, Any]) -> ScoringResult:
        """
        Evaluate one scoring input. Returns exactly one of:
            SCORED_OPPORTUNITY, NO_SCORE, or PROCESSING_FAILURE.

        Contract §3, §8.
        """
        # Defensively extract identifiers so every failure path can populate
        # pipeline_execution_id / pair_id / product_id on the failure result.
        pipeline_execution_id: str | None = None
        pair_id: str | None = None
        product_id: str | None = None

        try:
            # -----------------------------------------------------------
            # 1. Input parse — must be a dict.
            # -----------------------------------------------------------
            if not isinstance(scoring_input, dict):
                raise _ScoringError(
                    reason=FailureReason.INVALID_DISCREPANCY_INPUT,
                    stage=FailureStage.INPUT_PARSE,
                    context=(
                        f"Scoring input must be a dict. "
                        f"Received {type(scoring_input).__name__}."
                    ),
                    retriable=False,
                )

            # Early defensive extraction of identifiers (may still be None).
            pipeline_execution_id = scoring_input.get("pipeline_execution_id")
            pair_id               = scoring_input.get("pair_id")
            product_id            = scoring_input.get("product_id")

            logger.info(
                "scoring_worker_start",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "pair_id": pair_id,
                    "product_id": product_id,
                    "factor_count": (
                        len(scoring_input.get("scoring_factors") or [])
                    ),
                    "score_range": scoring_input.get("score_range"),
                },
            )

            # -----------------------------------------------------------
            # 2. Precondition check — Contract §5.
            # -----------------------------------------------------------
            self._check_preconditions(scoring_input)
            logger.debug(
                "scoring_worker_preconditions_passed",
                extra={"pipeline_execution_id": pipeline_execution_id},
            )

            # -----------------------------------------------------------
            # 3. Bind validated fields.
            # -----------------------------------------------------------
            pipeline_execution_id = scoring_input["pipeline_execution_id"]
            pair_id               = scoring_input["pair_id"]
            product_id            = scoring_input["product_id"]

            source_a            = scoring_input["source_a"]
            source_b            = scoring_input["source_b"]
            price_a             = float(scoring_input["price_a"])
            price_b             = float(scoring_input["price_b"])
            absolute_difference = float(scoring_input["absolute_difference"])
            percentage_difference = float(scoring_input["percentage_difference"])
            threshold_method    = scoring_input["threshold_method"]

            obs_ts_a = _parse_iso8601(
                scoring_input["observation_timestamp_a"],
                field_name="observation_timestamp_a",
            )
            obs_ts_b = _parse_iso8601(
                scoring_input["observation_timestamp_b"],
                field_name="observation_timestamp_b",
            )
            freshness_ref_ts_raw = scoring_input["freshness_reference_timestamp"]
            freshness_ref_ts = _parse_iso8601(
                freshness_ref_ts_raw,
                field_name="freshness_reference_timestamp",
            )

            scoring_timestamp_raw = scoring_input["scoring_timestamp"]
            # Validate format but preserve original string for output (§8.1).
            _parse_iso8601(
                scoring_timestamp_raw, field_name="scoring_timestamp"
            )

            scoring_factors: list[dict]   = scoring_input["scoring_factors"]
            score_range: dict             = scoring_input["score_range"]
            normalization_method: str | None = scoring_input.get(
                "normalization_method"
            )
            tie_break_order: list[str]    = list(
                scoring_input.get("tie_break_order") or []
            )

            score_min = float(score_range["min"])
            score_max = float(score_range["max"])

            # -----------------------------------------------------------
            # 4. Per-factor computation — Contract §7.1, §7.2, §7.3, §7.4.
            # -----------------------------------------------------------
            factors_applied: list[FactorApplied] = []
            weights_sum_accum = 0.0

            for factor_def in scoring_factors:
                factor = self._apply_factor(
                    factor_def=factor_def,
                    absolute_difference=absolute_difference,
                    percentage_difference=percentage_difference,
                    observation_timestamp_a=obs_ts_a,
                    observation_timestamp_b=obs_ts_b,
                    freshness_reference_timestamp=freshness_ref_ts,
                    score_min=score_min,
                    score_max=score_max,
                    normalization_method=normalization_method,
                )
                factors_applied.append(factor)
                weights_sum_accum += factor.weight

                logger.info(
                    "scoring_worker_factor_computed",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "factor_name": factor.factor_name,
                        "factor_type": factor.factor_type,
                        "raw_value": factor.raw_value,
                        "normalized_value": factor.normalized_value,
                        "weight": factor.weight,
                        "weighted_contribution": factor.weighted_contribution,
                    },
                )

            # -----------------------------------------------------------
            # 5. Weight-sum validation — Contract §7.3, §9.2.
            # Valid totals per spec: 1.0 (fractional) OR an equivalent
            # proportional integer total. Both forms are accepted to match
            # the configuration semantics the spec allows.
            # -----------------------------------------------------------
            weights_sum = weights_sum_accum
            if not self._is_valid_weight_total(weights_sum, scoring_factors):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.SCORE_ASSEMBLY,
                    context=(
                        f"Weights do not sum to a valid total. "
                        f"Sum observed: {weights_sum}. "
                        f"Valid totals are 1.0 (fractional) or the integer total "
                        f"implied by the configured weights."
                    ),
                    retriable=False,
                )

            # -----------------------------------------------------------
            # 6. Score assembly — Contract §7.3.
            # -----------------------------------------------------------
            raw_score = sum(f.weighted_contribution for f in factors_applied)

            if not math.isfinite(raw_score):
                raise _ScoringError(
                    reason=FailureReason.INVALID_FACTOR_VALUE,
                    stage=FailureStage.SCORE_ASSEMBLY,
                    context=(
                        f"Raw score is non-finite ({raw_score}). "
                        "Inspect factor computations."
                    ),
                    retriable=False,
                )

            # Clamp to [score_min, score_max] per §7.3.
            clamped = False
            if raw_score < score_min:
                final_score = score_min
                clamped = True
            elif raw_score > score_max:
                final_score = score_max
                clamped = True
            else:
                final_score = raw_score

            logger.info(
                "scoring_worker_score_assembled",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "raw_score": raw_score,
                    "final_score": final_score,
                    "clamped": clamped,
                },
            )

            # -----------------------------------------------------------
            # 7. Build SCORED_OPPORTUNITY — Contract §8.1.
            # -----------------------------------------------------------
            discrepancy_reference = {
                "source_a": source_a,
                "source_b": source_b,
                "price_a": price_a,
                "price_b": price_b,
                "absolute_difference": absolute_difference,
                "percentage_difference": percentage_difference,
                "threshold_method": threshold_method,
            }

            score_result_id = _derive_score_result_id(
                pipeline_execution_id=pipeline_execution_id,
                pair_id=pair_id,
            )

            result = ScoredOpportunityResult(
                result=ScoringResultType.SCORED_OPPORTUNITY.value,
                pipeline_execution_id=pipeline_execution_id,
                score_result_id=score_result_id,
                product_id=product_id,
                pair_id=pair_id,
                discrepancy_reference=discrepancy_reference,
                score=final_score,
                score_range={"min": score_min, "max": score_max},
                factors_applied=tuple(factors_applied),
                weights_sum=weights_sum,
                normalization_method=normalization_method,
                score_clamped=clamped,
                tie_break_order=tuple(tie_break_order),
                freshness_reference_timestamp=str(freshness_ref_ts_raw),
                scoring_timestamp=str(scoring_timestamp_raw),
            )

            logger.info(
                "scoring_worker_end",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "result": result.result,
                    "score": result.score,
                },
            )
            return result

        except _ScoringError as err:
            # Classified failure path — surface with full context.
            logger.warning(
                "scoring_worker_failure",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "pair_id": pair_id,
                    "product_id": product_id,
                    "failure_reason": err.reason.value,
                    "failure_stage": err.stage.value,
                    "retriable": err.retriable,
                    "error_context": err.context,
                },
            )
            return ProcessingFailureResult(
                result=ScoringResultType.PROCESSING_FAILURE.value,
                pipeline_execution_id=pipeline_execution_id,
                pair_id=pair_id,
                product_id=product_id,
                failure_reason=err.reason.value,
                failure_stage=err.stage.value,
                retriable=err.retriable,
                error_context=err.context,
            )

        except Exception as exc:
            # Unclassified runtime error — Contract §9.4.
            reason = (
                f"Unexpected runtime error in SCORING_WORKER: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.error(
                "scoring_worker_unexpected_error",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "pair_id": pair_id,
                    "product_id": product_id,
                    "error_context": reason,
                },
                exc_info=True,
            )
            return ProcessingFailureResult(
                result=ScoringResultType.PROCESSING_FAILURE.value,
                pipeline_execution_id=pipeline_execution_id,
                pair_id=pair_id,
                product_id=product_id,
                failure_reason=FailureReason.UNEXPECTED_RUNTIME_ERROR.value,
                failure_stage=FailureStage.SCORE_ASSEMBLY.value,
                retriable=True,   # §9.4: treat as potentially transient.
                error_context=reason,
            )

    # ------------------------------------------------------------------
    # Precondition checks — Contract §5
    # ------------------------------------------------------------------

    def _check_preconditions(self, ctx: dict) -> None:
        """
        Verify the eight preconditions from Contract §5. Raises _ScoringError
        with the correct failure reason on any violation.

        Reasons (Contract §5, §8.3, §9):
            - discrepancy_result ≠ DISCREPANCY_DETECTED → PRECONDITION_VIOLATION
            - malformed / missing required fields         → INVALID_DISCREPANCY_INPUT
            - invalid scoring configuration               → INVALID_SCORING_CONFIGURATION
            - non-positive / non-finite prices            → PRECONDITION_VIOLATION
            - timestamps missing / malformed / ordered wrong → PRECONDITION_VIOLATION
            - missing pipeline_execution_id               → PRECONDITION_VIOLATION
        """
        # --- §5.8 pipeline_execution_id present ------------------------
        pid = ctx.get("pipeline_execution_id")
        if not pid or not isinstance(pid, str):
            raise _ScoringError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context="Precondition §5.8: 'pipeline_execution_id' absent or empty.",
                retriable=False,
            )

        # --- Required discrepancy-identifier fields (§4) ---------------
        for required in (
            "pair_id",
            "product_id",
            "source_a",
            "source_b",
            "threshold_method",
            "lower_price_source",
            "higher_price_source",
        ):
            val = ctx.get(required)
            if not val or not isinstance(val, str):
                raise _ScoringError(
                    reason=FailureReason.INVALID_DISCREPANCY_INPUT,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Required discrepancy field '{required}' is absent, "
                        f"null, or not a non-empty string."
                    ),
                    retriable=False,
                )

        # --- §5.1 discrepancy_result must be DISCREPANCY_DETECTED -----
        discrepancy_result = ctx.get("discrepancy_result")
        if discrepancy_result != "DISCREPANCY_DETECTED":
            raise _ScoringError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.1: 'discrepancy_result' must be "
                    f"'DISCREPANCY_DETECTED'. Received {discrepancy_result!r}."
                ),
                retriable=False,
            )

        # --- §5.5 prices positive, finite ------------------------------
        for field_name in ("price_a", "price_b"):
            val = ctx.get(field_name)
            if (
                val is None
                or isinstance(val, bool)
                or not isinstance(val, (int, float))
            ):
                raise _ScoringError(
                    reason=FailureReason.INVALID_DISCREPANCY_INPUT,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Required price field '{field_name}' is absent or "
                        f"not numeric (not bool)."
                    ),
                    retriable=False,
                )
            fval = float(val)
            if not math.isfinite(fval) or fval <= 0:
                raise _ScoringError(
                    reason=FailureReason.PRECONDITION_VIOLATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.5: '{field_name}' must be a positive, "
                        f"finite number. Received {val!r}."
                    ),
                    retriable=False,
                )

        # Precomputed differences must be numeric (Contract §7.1, §7.2:
        # the worker uses them as-is and must not recompute).
        for field_name in ("absolute_difference", "percentage_difference"):
            val = ctx.get(field_name)
            if (
                val is None
                or isinstance(val, bool)
                or not isinstance(val, (int, float))
                or not math.isfinite(float(val))
            ):
                raise _ScoringError(
                    reason=FailureReason.INVALID_DISCREPANCY_INPUT,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Required numeric field '{field_name}' is absent, "
                        f"non-numeric, or non-finite."
                    ),
                    retriable=False,
                )

        # --- §5.6 observation timestamps ISO 8601 ---------------------
        obs_ts_a = _parse_iso8601(
            ctx.get("observation_timestamp_a"),
            field_name="observation_timestamp_a",
        )
        obs_ts_b = _parse_iso8601(
            ctx.get("observation_timestamp_b"),
            field_name="observation_timestamp_b",
        )

        # --- §5.7 freshness_reference_timestamp present, valid, ≥ both --
        freshness_ref_ts = _parse_iso8601(
            ctx.get("freshness_reference_timestamp"),
            field_name="freshness_reference_timestamp",
        )
        if freshness_ref_ts < obs_ts_a or freshness_ref_ts < obs_ts_b:
            raise _ScoringError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.7: 'freshness_reference_timestamp' must "
                    "not be earlier than either observation timestamp. "
                    f"ref={freshness_ref_ts.isoformat()}, "
                    f"obs_a={obs_ts_a.isoformat()}, "
                    f"obs_b={obs_ts_b.isoformat()}."
                ),
                retriable=False,
            )

        # --- §10.10 scoring_timestamp must be passed in ---------------
        scoring_ts_raw = ctx.get("scoring_timestamp")
        if scoring_ts_raw is None:
            raise _ScoringError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §10.10: 'scoring_timestamp' must be passed in. "
                    "The worker must not derive it from the system clock."
                ),
                retriable=False,
            )
        _parse_iso8601(scoring_ts_raw, field_name="scoring_timestamp")

        # --- §5.4 score_range valid -----------------------------------
        score_range = ctx.get("score_range")
        if not isinstance(score_range, dict):
            raise _ScoringError(
                reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.4: 'score_range' must be an object with "
                    "numeric 'min' and 'max'."
                ),
                retriable=False,
            )
        s_min = score_range.get("min")
        s_max = score_range.get("max")
        for name, val in (("min", s_min), ("max", s_max)):
            if (
                val is None
                or isinstance(val, bool)
                or not isinstance(val, (int, float))
                or not math.isfinite(float(val))
            ):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.4: 'score_range.{name}' must be a "
                        f"finite number. Received {val!r}."
                    ),
                    retriable=False,
                )
        if float(s_min) >= float(s_max):
            raise _ScoringError(
                reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.4: 'score_range.min' ({s_min}) must be "
                    f"strictly less than 'score_range.max' ({s_max})."
                ),
                retriable=False,
            )

        # --- §5.2 scoring_factors non-empty ---------------------------
        scoring_factors = ctx.get("scoring_factors")
        if not isinstance(scoring_factors, list) or len(scoring_factors) == 0:
            raise _ScoringError(
                reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.2: 'scoring_factors' must be a non-empty "
                    "list loaded from the spec-defined configuration."
                ),
                retriable=False,
            )

        # --- §5.3 each factor has explicit non-null weight, name, type -
        seen_names: set[str] = set()
        for i, fdef in enumerate(scoring_factors):
            if not isinstance(fdef, dict):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: scoring_factors[{i}] must be a "
                        f"dict. Received {type(fdef).__name__}."
                    ),
                    retriable=False,
                )
            name = fdef.get("factor_name")
            if not name or not isinstance(name, str):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: scoring_factors[{i}].factor_name "
                        f"is absent or not a non-empty string."
                    ),
                    retriable=False,
                )
            if name in seen_names:
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: duplicate factor_name "
                        f"{name!r} in scoring_factors."
                    ),
                    retriable=False,
                )
            seen_names.add(name)

            ftype = fdef.get("factor_type")
            if not ftype or not isinstance(ftype, str):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: scoring_factors[{i}].factor_type "
                        f"is absent or not a non-empty string."
                    ),
                    retriable=False,
                )

            weight = fdef.get("weight")
            if (
                weight is None
                or isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(float(weight))
            ):
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: scoring_factors[{i}].weight is "
                        f"absent, null, non-numeric, or non-finite."
                    ),
                    retriable=False,
                )
            if float(weight) < 0:
                raise _ScoringError(
                    reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.3: scoring_factors[{i}].weight must "
                        f"be >= 0. Received {weight}."
                    ),
                    retriable=False,
                )

    # ------------------------------------------------------------------
    # Per-factor computation — Contract §7.1, §7.2, §7.3, §7.4
    # ------------------------------------------------------------------

    def _apply_factor(
        self,
        factor_def: dict,
        absolute_difference: float,
        percentage_difference: float,
        observation_timestamp_a: datetime,
        observation_timestamp_b: datetime,
        freshness_reference_timestamp: datetime,
        score_min: float,
        score_max: float,
        normalization_method: str | None,
    ) -> FactorApplied:
        """
        Compute raw, normalized, and weighted contributions for one factor.

        Only factor types explicitly present in the configuration are applied
        (Contract §10.8). Unknown factor_type values raise
        INVALID_SCORING_CONFIGURATION — the worker never silently skips.
        """
        factor_name: str = factor_def["factor_name"]
        factor_type: str = factor_def["factor_type"]
        weight: float    = float(factor_def["weight"])

        # --- Raw factor value ----------------------------------------
        if factor_type == FactorType.ABSOLUTE_DIFFERENCE.value:
            # §7.1 — use precomputed value from discrepancy worker.
            raw_value = float(absolute_difference)

        elif factor_type == FactorType.PERCENTAGE_DIFFERENCE.value:
            # §7.2 — use precomputed value from discrepancy worker.
            raw_value = float(percentage_difference)

        elif factor_type == FactorType.FRESHNESS_DECAY.value:
            # §7.2 (freshness) — age in seconds from most recent observation
            # to the passed-in freshness_reference_timestamp.
            most_recent = max(
                observation_timestamp_a,
                observation_timestamp_b,
            )
            age_seconds = (
                freshness_reference_timestamp - most_recent
            ).total_seconds()
            if age_seconds < 0 or not math.isfinite(age_seconds):
                raise _ScoringError(
                    reason=FailureReason.INVALID_FACTOR_VALUE,
                    stage=FailureStage.FACTOR_COMPUTATION,
                    context=(
                        f"Freshness age computed as {age_seconds}s — reference "
                        f"timestamp predates the most recent observation. "
                        "This should have been caught in preconditions."
                    ),
                    retriable=False,
                )
            raw_value = float(age_seconds)

        else:
            # §10.8 — no factor invention, no silent skipping of unknown types.
            raise _ScoringError(
                reason=FailureReason.INVALID_SCORING_CONFIGURATION,
                stage=FailureStage.FACTOR_COMPUTATION,
                context=(
                    f"Unknown factor_type {factor_type!r} for factor "
                    f"{factor_name!r}. Supported types: "
                    f"{sorted(t.value for t in FactorType)}."
                ),
                retriable=False,
            )

        if not math.isfinite(raw_value):
            raise _ScoringError(
                reason=FailureReason.INVALID_FACTOR_VALUE,
                stage=FailureStage.FACTOR_COMPUTATION,
                context=(
                    f"Factor {factor_name!r} ({factor_type}) produced a "
                    f"non-finite raw value: {raw_value}."
                ),
                retriable=False,
            )

        # --- Normalization — Contract §7.4 ---------------------------
        normalized_value = self._normalize(
            raw_value=raw_value,
            factor_type=factor_type,
            normalization_method=normalization_method,
            score_min=score_min,
            score_max=score_max,
            factor_name=factor_name,
        )

        # --- Weighted contribution — Contract §7.3 -------------------
        weighted_contribution = weight * normalized_value

        if not math.isfinite(weighted_contribution):
            raise _ScoringError(
                reason=FailureReason.INVALID_FACTOR_VALUE,
                stage=FailureStage.FACTOR_COMPUTATION,
                context=(
                    f"Factor {factor_name!r} weighted contribution is "
                    f"non-finite: {weighted_contribution}."
                ),
                retriable=False,
            )

        return FactorApplied(
            factor_name=factor_name,
            factor_type=factor_type,
            raw_value=raw_value,
            normalized_value=normalized_value,
            weight=weight,
            weighted_contribution=weighted_contribution,
        )

    # ------------------------------------------------------------------
    # Normalization — Contract §7.4
    # ------------------------------------------------------------------

    def _normalize(
        self,
        raw_value: float,
        factor_type: str,
        normalization_method: str | None,
        score_min: float,
        score_max: float,
        factor_name: str,
    ) -> float:
        """
        Apply the configured normalization method to a raw factor value.

        §7.4 rules:
            - Deterministic: same input → same normalized output.
            - Documented: method name is recorded in the output.
            - Bounded: normalized values fall within score_range.
            - No implicit normalization: if `normalization_method` is None,
              the raw value is used as-is (§7.4 final paragraph).
            - No invented methods: unknown method names are an
              INVALID_SCORING_CONFIGURATION.
        """
        # No normalization configured — use raw as-is (§7.4).
        if normalization_method is None:
            return raw_value

        # Method: LINEAR_BOUNDED — maps raw_value into [score_min, score_max]
        # using a bounded identity:
        #   freshness_decay (lower raw value == fresher == higher normalized)
        #   other factors   (higher raw value == higher normalized)
        # Bounding is hard-clamped into the score_range.
        if normalization_method == "LINEAR_BOUNDED":
            if factor_type == FactorType.FRESHNESS_DECAY.value:
                # Age-to-freshness inversion: fresher → closer to score_max.
                # Bounded by construction: a negative age is forbidden
                # upstream; a very old age asymptotes to score_min.
                # Mapping: score_max / (1 + age_seconds) normalized into range.
                denom = 1.0 + raw_value
                if denom <= 0 or not math.isfinite(denom):
                    raise _ScoringError(
                        reason=FailureReason.INVALID_FACTOR_VALUE,
                        stage=FailureStage.FACTOR_COMPUTATION,
                        context=(
                            f"Normalization denominator non-positive for factor "
                            f"{factor_name!r}. raw_value={raw_value}."
                        ),
                        retriable=False,
                    )
                normalized = score_max / denom
            else:
                # Identity-then-clamp for difference factors.
                normalized = raw_value

            # §7.4 bounded requirement — clamp into [score_min, score_max].
            if normalized < score_min:
                normalized = score_min
            elif normalized > score_max:
                normalized = score_max
            return float(normalized)

        # Unknown normalization method — §7.4, §10.7: no invention.
        raise _ScoringError(
            reason=FailureReason.INVALID_SCORING_CONFIGURATION,
            stage=FailureStage.FACTOR_COMPUTATION,
            context=(
                f"Unknown normalization_method {normalization_method!r}. "
                "Worker must not invent a normalization method."
            ),
            retriable=False,
        )

    # ------------------------------------------------------------------
    # Weight-total validation — Contract §7.3, §9.2
    # ------------------------------------------------------------------

    def _is_valid_weight_total(
        self, weights_sum: float, scoring_factors: list[dict]
    ) -> bool:
        """
        Accept either:
            - a fractional total of 1.0 (within floating-point tolerance), or
            - an integer proportional total (every weight is an integer and
              the sum is a positive integer).

        Both forms are explicitly permitted by §7.3 ("1.0 or an equivalent
        proportional total if the configuration uses integer weights").
        """
        # Fractional (float) form — tolerance matches typical float precision.
        if math.isclose(weights_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9):
            return True

        # Integer proportional form — every declared weight is an int
        # (not a bool) and the accumulated sum is > 0 and integer-equal.
        all_integers = all(
            isinstance(f.get("weight"), int) and not isinstance(f.get("weight"), bool)
            for f in scoring_factors
        )
        if all_integers and weights_sum > 0 and float(int(weights_sum)) == weights_sum:
            return True

        return False


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_iso8601(value: Any, *, field_name: str) -> datetime:
    """
    Parse an ISO 8601 timestamp string or datetime into a datetime instance.

    Raises _ScoringError with classification INVALID_DISCREPANCY_INPUT or
    PRECONDITION_VIOLATION as appropriate if the value is missing or malformed.
    """
    if value is None:
        raise _ScoringError(
            reason=FailureReason.PRECONDITION_VIOLATION,
            stage=FailureStage.PRECONDITION_CHECK,
            context=f"Required timestamp field '{field_name}' is absent.",
            retriable=False,
        )

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise _ScoringError(
            reason=FailureReason.INVALID_DISCREPANCY_INPUT,
            stage=FailureStage.PRECONDITION_CHECK,
            context=(
                f"Timestamp field '{field_name}' must be an ISO 8601 string "
                f"or a datetime. Received {type(value).__name__}."
            ),
            retriable=False,
        )

    try:
        # fromisoformat handles offsets; normalize trailing "Z" to "+00:00".
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _ScoringError(
            reason=FailureReason.INVALID_DISCREPANCY_INPUT,
            stage=FailureStage.PRECONDITION_CHECK,
            context=(
                f"Timestamp field '{field_name}' is not a valid ISO 8601 "
                f"string: {value!r} ({exc})."
            ),
            retriable=False,
        ) from exc


def _derive_score_result_id(*, pipeline_execution_id: str, pair_id: str) -> str:
    """
    Derive a deterministic `score_result_id` from pipeline_execution_id and
    pair_id (Contract §8.1, §11.2, §15).

    The form is intentionally trivial: a stable concatenation. The pipeline
    coordinator is the sole arbiter of uniqueness across executions (§11.3).
    """
    return f"score::{pipeline_execution_id}::{pair_id}"
