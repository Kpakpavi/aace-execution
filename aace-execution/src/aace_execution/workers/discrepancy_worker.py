"""
Discrepancy Worker — Stage 2 of the AACE Opportunity Pipeline.

Contract: Contracts/DISCREPANCY_WORKER_CONTRACT.md

Determines with certainty whether a meaningful price discrepancy exists across
the price observations in a normalized input context, using only the rules
defined in the configured discrepancy rule set.

Determinism guarantee (Contract §10):
    The same normalized_context + the same rule set always produce the same
    DiscrepancyResult. The system clock is never consulted. No randomness.
    No external calls.

What this worker does NOT do (Contract §13):
    - Score opportunities.
    - Trigger alerts.
    - Fetch, modify, enrich, or persist any data.
    - Normalize prices or convert currencies.
    - Call any AI model at runtime.
    - Apply rules not in the spec.
    - Produce partial results.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result classification — Contract §8
# ---------------------------------------------------------------------------

class DiscrepancyResultType(str, Enum):
    """
    The three and only three result states the worker may produce.
    Contract §8: no other state exists.
    """
    DISCREPANCY_DETECTED = "DISCREPANCY_DETECTED"
    NO_DISCREPANCY = "NO_DISCREPANCY"
    PROCESSING_FAILURE = "PROCESSING_FAILURE"


# ---------------------------------------------------------------------------
# Threshold methods — Contract §4.3
# ---------------------------------------------------------------------------

class ThresholdMethod(str, Enum):
    """
    Threshold evaluation strategies supported by the discrepancy rule set.
    Contract §4.3, §7.3.
    """
    ABSOLUTE = "ABSOLUTE"
    PERCENTAGE = "PERCENTAGE"
    BOTH = "BOTH"


# ---------------------------------------------------------------------------
# Noise filter identifiers — Contract §7.5
#
# Filters are numbered exactly as they appear in §7.5.
# The implementation applies pre-computation guards (4, 5, 6, 7) before
# arithmetic is attempted, then applies post-computation filters (1, 2, 3)
# in their documented order. This ordering is fixed and identical on every run
# — satisfying the determinism requirement in §10.8 — and is the only
# physically safe ordering given that filters 1–3 require computed values
# while filter 4 guards against the zero-price division error described in §9.4.
# ---------------------------------------------------------------------------

class NoiseFilter(str, Enum):
    """
    Named identifiers for the seven noise-filter rules in Contract §7.5.
    Every skipped pair must reference one of these.
    """
    ZERO_DIFFERENCE           = "NOISE_FILTER_1_ZERO_DIFFERENCE"
    BELOW_ABSOLUTE_THRESHOLD  = "NOISE_FILTER_2_BELOW_ABSOLUTE_THRESHOLD"
    BELOW_PERCENTAGE_THRESHOLD = "NOISE_FILTER_3_BELOW_PERCENTAGE_THRESHOLD"
    PRICE_NOT_POSITIVE        = "NOISE_FILTER_4_PRICE_NOT_POSITIVE"
    SAME_SOURCE               = "NOISE_FILTER_5_SAME_SOURCE"
    UNRELATED_PRODUCT_CONTEXT = "NOISE_FILTER_6_UNRELATED_PRODUCT_CONTEXT"
    CURRENCY_MISMATCH         = "NOISE_FILTER_7_CURRENCY_MISMATCH"


# ---------------------------------------------------------------------------
# Per-pair result — Contract §8.1 (pair result table)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PairResult:
    """
    Full evaluation detail for a single canonical source pair.
    Included in every result type, including skipped pairs (Contract §8.2).

    Fields that cannot be computed (because a pre-computation filter fired)
    are set to None. This is not an error — it signals that arithmetic was
    never attempted for this pair.
    """
    pair_id: str
    source_a: str                        # lexicographically lesser source (§6.2)
    source_b: str
    observation_id_a: str
    observation_id_b: str
    price_a: float | None                # None when filter 4/5/6/7 fires first
    price_b: float | None
    absolute_difference: float | None    # None when pre-computation filter fires
    percentage_difference: float | None  # None when pre-computation filter fires
    absolute_threshold_used: float | None
    percentage_threshold_used: float | None
    lower_price_source: str | None       # None when prices are equal or not computed
    higher_price_source: str | None
    pair_result: str                     # DISCREPANCY_DETECTED or NO_DISCREPANCY
    threshold_met: bool
    skip_reason: str | None = None       # populated when any noise filter fires


# ---------------------------------------------------------------------------
# Top-level result dataclasses — Contract §8.1, §8.2, §8.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscrepancyDetectedResult:
    """
    Returned when at least one eligible pair crosses the configured threshold.
    Contract §8.1.
    """
    result: str                           # always DiscrepancyResultType.DISCREPANCY_DETECTED
    product_id: str
    pipeline_execution_id: str
    evaluation_reference_timestamp: datetime
    rule_id: str
    threshold_method: str
    pairs_evaluated: int
    pairs_with_discrepancy: int
    pair_results: tuple[PairResult, ...]


@dataclass(frozen=True)
class NoDiscrepancyResult:
    """
    Returned when all eligible pairs were evaluated and none crossed the threshold,
    or when all pairs were excluded by noise filters.
    Contract §8.2.
    """
    result: str                           # always DiscrepancyResultType.NO_DISCREPANCY
    product_id: str
    pipeline_execution_id: str
    evaluation_reference_timestamp: datetime
    rule_id: str
    threshold_method: str
    pairs_evaluated: int
    pairs_skipped: int                    # pairs excluded by any noise filter
    pair_results: tuple[PairResult, ...]


@dataclass(frozen=True)
class ProcessingFailureResult:
    """
    Returned when a precondition fails or an unexpected runtime error occurs.
    Contract §8.3.
    """
    result: str                           # always DiscrepancyResultType.PROCESSING_FAILURE
    product_id: str | None                # None when not extractable from context
    pipeline_execution_id: str
    evaluation_reference_timestamp: datetime | None  # None when not extractable
    failure_stage: str                    # always "DISCREPANCY_WORKER"
    failure_reason: str
    retriable: bool


# Union type for return annotations
DiscrepancyResult = DiscrepancyDetectedResult | NoDiscrepancyResult | ProcessingFailureResult


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

class DiscrepancyWorker:
    """
    Evaluates a normalized input context for price discrepancies across
    distinct sources.

    The worker is stateless. Call ``evaluate()`` once per pipeline execution
    instance. The same context + rule set always returns the same result.

    Usage::

        worker = DiscrepancyWorker()
        result = worker.evaluate(normalized_context)
    """

    def evaluate(self, normalized_context: dict[str, Any]) -> DiscrepancyResult:
        """
        Main entry point. Returns exactly one of:
            DISCREPANCY_DETECTED, NO_DISCREPANCY, or PROCESSING_FAILURE.

        Contract §3, §8.
        """
        # ----------------------------------------------------------------
        # Extract envelope fields before any validation so every failure
        # path can populate them in the PROCESSING_FAILURE result.
        # These are read defensively — they may be absent or wrong type.
        # ----------------------------------------------------------------
        product_id: str | None = None
        pipeline_execution_id: str = "<unknown>"
        eval_ts: datetime | None = None

        try:
            if isinstance(normalized_context, dict):
                product_id = normalized_context.get("product_id")
                pipeline_execution_id = normalized_context.get(
                    "pipeline_execution_id", "<unknown>"
                ) or "<unknown>"
                eval_ts = normalized_context.get("evaluation_reference_timestamp")

            logger.info(
                "discrepancy_worker_start",
                extra={
                    "product_id": product_id,
                    "pipeline_execution_id": pipeline_execution_id,
                    "observation_count": (
                        len(normalized_context.get("observations", []))
                        if isinstance(normalized_context, dict)
                        else 0
                    ),
                    "evaluation_reference_timestamp": str(eval_ts),
                },
            )

            # ----------------------------------------------------------------
            # Precondition checks — Contract §5.
            # Any failure → PROCESSING_FAILURE with retriable=False.
            # These are pipeline errors, not new validation failures (§5 intro).
            # ----------------------------------------------------------------
            precondition_error = self._check_preconditions(normalized_context)
            if precondition_error:
                logger.warning(
                    "discrepancy_worker_precondition_failure",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "product_id": product_id,
                        "reason": precondition_error,
                        "retriable": False,
                    },
                )
                return ProcessingFailureResult(
                    result=DiscrepancyResultType.PROCESSING_FAILURE.value,
                    product_id=product_id,
                    pipeline_execution_id=pipeline_execution_id,
                    evaluation_reference_timestamp=eval_ts,
                    failure_stage="DISCREPANCY_WORKER",
                    failure_reason=precondition_error,
                    retriable=False,
                )

            # ----------------------------------------------------------------
            # Extract validated fields — safe after preconditions pass.
            # ----------------------------------------------------------------
            observations: list[dict]      = normalized_context["observations"]
            rule_set: dict                = normalized_context["discrepancy_rule_set"]
            evaluation_reference_timestamp: datetime = normalized_context[
                "evaluation_reference_timestamp"
            ]
            pipeline_execution_id = normalized_context["pipeline_execution_id"]
            product_id            = normalized_context["product_id"]

            rule_id: str             = rule_set["rule_id"]
            threshold_method: str    = rule_set["threshold_method"]
            absolute_threshold: float | None  = rule_set.get("absolute_threshold")
            percentage_threshold: float | None = rule_set.get("percentage_threshold")

            # ----------------------------------------------------------------
            # Build canonical source pairs — Contract §6.2, §10.3.
            # Pairs are sorted lexicographically by (source_a, source_b).
            # A/B and B/A are never both produced for the same two sources.
            # ----------------------------------------------------------------
            canonical_pairs = self._build_canonical_pairs(observations)

            logger.debug(
                "discrepancy_worker_pair_construction",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "pairs_count": len(canonical_pairs),
                },
            )

            # ----------------------------------------------------------------
            # Evaluate each canonical pair against the rule set — Contract §7.
            # ----------------------------------------------------------------
            pair_results: list[PairResult] = []
            for obs_a, obs_b in canonical_pairs:
                pr = self._evaluate_pair(
                    obs_a=obs_a,
                    obs_b=obs_b,
                    threshold_method=threshold_method,
                    absolute_threshold=absolute_threshold,
                    percentage_threshold=percentage_threshold,
                    pipeline_execution_id=pipeline_execution_id,
                )
                pair_results.append(pr)

            # ----------------------------------------------------------------
            # Aggregate — Contract §6.4:
            #   any DISCREPANCY_DETECTED pair → overall DISCREPANCY_DETECTED.
            #   all NO_DISCREPANCY pairs       → overall NO_DISCREPANCY.
            # ----------------------------------------------------------------
            pairs_evaluated        = len(pair_results)
            pairs_with_discrepancy = sum(1 for pr in pair_results if pr.threshold_met)
            pairs_skipped          = sum(
                1 for pr in pair_results if pr.skip_reason is not None
            )

            overall = (
                DiscrepancyResultType.DISCREPANCY_DETECTED
                if pairs_with_discrepancy > 0
                else DiscrepancyResultType.NO_DISCREPANCY
            )

            logger.info(
                "discrepancy_worker_end",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "overall_result": overall.value,
                    "pairs_evaluated": pairs_evaluated,
                    "pairs_with_discrepancy": pairs_with_discrepancy,
                    "pairs_skipped": pairs_skipped,
                    "evaluation_reference_timestamp": str(
                        evaluation_reference_timestamp
                    ),
                },
            )

            if overall == DiscrepancyResultType.DISCREPANCY_DETECTED:
                return DiscrepancyDetectedResult(
                    result=overall.value,
                    product_id=product_id,
                    pipeline_execution_id=pipeline_execution_id,
                    evaluation_reference_timestamp=evaluation_reference_timestamp,
                    rule_id=rule_id,
                    threshold_method=threshold_method,
                    pairs_evaluated=pairs_evaluated,
                    pairs_with_discrepancy=pairs_with_discrepancy,
                    pair_results=tuple(pair_results),
                )
            else:
                return NoDiscrepancyResult(
                    result=overall.value,
                    product_id=product_id,
                    pipeline_execution_id=pipeline_execution_id,
                    evaluation_reference_timestamp=evaluation_reference_timestamp,
                    rule_id=rule_id,
                    threshold_method=threshold_method,
                    pairs_evaluated=pairs_evaluated,
                    pairs_skipped=pairs_skipped,
                    pair_results=tuple(pair_results),
                )

        except Exception as exc:
            # ----------------------------------------------------------------
            # Contract §9.5 — Unexpected runtime error.
            # Surface the exception explicitly with context.
            # Default retriable=False per §9.5.
            # ----------------------------------------------------------------
            reason = (
                f"Unexpected runtime error in DISCREPANCY_WORKER: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.error(
                "discrepancy_worker_unexpected_error",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "product_id": product_id,
                    "reason": reason,
                    "retriable": False,
                },
                exc_info=True,
            )
            return ProcessingFailureResult(
                result=DiscrepancyResultType.PROCESSING_FAILURE.value,
                product_id=product_id,
                pipeline_execution_id=pipeline_execution_id,
                evaluation_reference_timestamp=eval_ts,
                failure_stage="DISCREPANCY_WORKER",
                failure_reason=reason,
                retriable=False,
            )

    # ------------------------------------------------------------------
    # Precondition checks — Contract §5
    # ------------------------------------------------------------------

    def _check_preconditions(self, ctx: Any) -> str | None:
        """
        Verify all six preconditions from Contract §5.

        Returns a human-readable failure description if any precondition is
        not satisfied, or None if all pass.

        A failure here surfaces as PROCESSING_FAILURE (retriable=False) because
        a failed precondition indicates a pipeline defect in an earlier stage,
        not a transient error (§5 intro, §9.1, §9.2).
        """
        if not isinstance(ctx, dict):
            return (
                f"Normalized context must be a dict. "
                f"Received {type(ctx).__name__}."
            )

        # §5.6 — pipeline_execution_id present and non-empty
        pid = ctx.get("pipeline_execution_id")
        if not pid or not isinstance(pid, str):
            return "Precondition §5.6: 'pipeline_execution_id' is absent or empty."

        # §5.5 — evaluation_reference_timestamp present and a datetime
        eval_ts = ctx.get("evaluation_reference_timestamp")
        if eval_ts is None:
            return (
                "Precondition §5.5: 'evaluation_reference_timestamp' is absent. "
                "The worker must not derive a timestamp from the system clock."
            )
        if not isinstance(eval_ts, datetime):
            return (
                f"Precondition §5.5: 'evaluation_reference_timestamp' must be a "
                f"datetime object. Received {type(eval_ts).__name__}."
            )

        # §4.1 — product fields
        product_id = ctx.get("product_id")
        if not product_id or not isinstance(product_id, str):
            return "Precondition §4.1: 'product_id' is absent or empty."

        product_name = ctx.get("product_name")
        if not product_name or not isinstance(product_name, str):
            return "Precondition §4.1: 'product_name' is absent or empty."

        # §5.4 — discrepancy rule set non-null and non-empty
        rule_set = ctx.get("discrepancy_rule_set")
        if not rule_set or not isinstance(rule_set, dict):
            return (
                "Precondition §5.4: 'discrepancy_rule_set' is absent, null, "
                "empty, or not a dict."
            )

        rule_id = rule_set.get("rule_id")
        if not rule_id or not isinstance(rule_id, str):
            return "Precondition §5.4: 'discrepancy_rule_set.rule_id' is absent or empty."

        threshold_method = rule_set.get("threshold_method")
        valid_methods = {m.value for m in ThresholdMethod}
        if threshold_method not in valid_methods:
            return (
                f"Precondition §5.4: 'discrepancy_rule_set.threshold_method' must be "
                f"one of {sorted(valid_methods)}. Received {threshold_method!r}."
            )

        # Validate threshold values based on the method
        if threshold_method in (ThresholdMethod.ABSOLUTE.value, ThresholdMethod.BOTH.value):
            abs_thresh = rule_set.get("absolute_threshold")
            if (
                abs_thresh is None
                or isinstance(abs_thresh, bool)
                or not isinstance(abs_thresh, (int, float))
            ):
                return (
                    "Precondition §5.4: 'discrepancy_rule_set.absolute_threshold' is "
                    "required for ABSOLUTE or BOTH method and must be numeric (not bool)."
                )
            if abs_thresh <= 0:
                return (
                    f"Precondition §5.4: 'discrepancy_rule_set.absolute_threshold' must "
                    f"be > 0. Received {abs_thresh}."
                )

        if threshold_method in (ThresholdMethod.PERCENTAGE.value, ThresholdMethod.BOTH.value):
            pct_thresh = rule_set.get("percentage_threshold")
            if (
                pct_thresh is None
                or isinstance(pct_thresh, bool)
                or not isinstance(pct_thresh, (int, float))
            ):
                return (
                    "Precondition §5.4: 'discrepancy_rule_set.percentage_threshold' is "
                    "required for PERCENTAGE or BOTH method and must be numeric (not bool)."
                )
            if pct_thresh <= 0:
                return (
                    f"Precondition §5.4: 'discrepancy_rule_set.percentage_threshold' must "
                    f"be > 0. Received {pct_thresh}."
                )

        # §5.1 — at least two observations
        observations = ctx.get("observations")
        if not isinstance(observations, list):
            return (
                f"Precondition §5.1: 'observations' must be a list. "
                f"Received {type(observations).__name__}."
            )
        if len(observations) < 2:
            return (
                f"Precondition §5.1: at least two observations are required. "
                f"Received {len(observations)}."
            )

        # §4.2 — validate each observation's required fields and prices
        distinct_sources: set[str] = set()
        for i, obs in enumerate(observations):
            if not isinstance(obs, dict):
                return (
                    f"Precondition §4.2: observations[{i}] must be a dict. "
                    f"Received {type(obs).__name__}."
                )
            for str_field in ("observation_id", "source", "listing_ref"):
                val = obs.get(str_field)
                if not val or not isinstance(val, str):
                    return (
                        f"Precondition §4.2: observations[{i}].{str_field} is "
                        f"absent, null, or not a non-empty string."
                    )

            if obs.get("observed_at") is None:
                return f"Precondition §4.2: observations[{i}].observed_at is absent."

            # §5.3 — normalized_price strictly > 0
            price = obs.get("normalized_price")
            if (
                price is None
                or isinstance(price, bool)
                or not isinstance(price, (int, float))
            ):
                return (
                    f"Precondition §5.3: observations[{i}].normalized_price is "
                    f"absent or not numeric (not bool)."
                )
            if price <= 0:
                return (
                    f"Precondition §5.3: observations[{i}].normalized_price must "
                    f"be > 0. Received {price}."
                )

            distinct_sources.add(obs["source"])

        # §5.1 — at least two DISTINCT source identifiers
        if len(distinct_sources) < 2:
            sole = next(iter(distinct_sources)) if distinct_sources else "<none>"
            return (
                f"Precondition §5.1: at least two distinct source identifiers are "
                f"required. Only one found: {sole!r}."
            )

        return None  # All preconditions satisfied

    # ------------------------------------------------------------------
    # Canonical pair construction — Contract §6.2, §10.3
    # ------------------------------------------------------------------

    def _build_canonical_pairs(
        self, observations: list[dict]
    ) -> list[tuple[dict, dict]]:
        """
        Build every distinct-source pair from the observation list.

        Canonical ordering rule (§6.2):
            The observation whose source identifier is lexicographically lesser
            is always obs_a. This prevents (A, B) and (B, A) from both appearing.

        Pair ordering in the returned list (§10.3):
            Pairs are sorted by pair_id (i.e., "{source_a}::{source_b}") so the
            output order is stable and independent of observation list order.

        Duplicate pair_ids (same two sources appearing more than once, which
        Stage 1 validation should prevent) are collapsed to the first occurrence.
        """
        seen_pair_ids: set[str] = set()
        pairs: list[tuple[dict, dict]] = []

        for raw_a, raw_b in itertools.combinations(observations, 2):
            src_x = raw_a.get("source", "")
            src_y = raw_b.get("source", "")

            # Canonical: lesser source is always obs_a
            if src_x <= src_y:
                obs_a, obs_b = raw_a, raw_b
            else:
                obs_a, obs_b = raw_b, raw_a

            pair_id = _pair_id(obs_a["source"], obs_b["source"])

            if pair_id in seen_pair_ids:
                # Duplicate source pair — already covered; skip silently.
                # (Stage 1 should have rejected duplicate source observations.)
                continue
            seen_pair_ids.add(pair_id)
            pairs.append((obs_a, obs_b))

        # Sort by pair_id for fully deterministic output ordering (§10.3)
        pairs.sort(key=lambda p: _pair_id(p[0]["source"], p[1]["source"]))
        return pairs

    # ------------------------------------------------------------------
    # Per-pair evaluation — Contract §7
    # ------------------------------------------------------------------

    def _evaluate_pair(
        self,
        obs_a: dict,
        obs_b: dict,
        threshold_method: str,
        absolute_threshold: float | None,
        percentage_threshold: float | None,
        pipeline_execution_id: str,
    ) -> PairResult:
        """
        Evaluate a single canonical pair (obs_a.source < obs_b.source) against
        the configured rule set.

        Noise filter application order (fixed per §7.5, §10.8):

            Pre-computation guards (arithmetic would be unsafe or meaningless):
                Filter 4 — price not positive (§7.5.4)
                Filter 5 — same source       (§7.5.5)
                Filter 6 — unrelated product context (§7.5.6)
                Filter 7 — currency mismatch (§7.5.7)

            Arithmetic: absolute_difference (§7.1), percentage_difference (§7.2)

            Post-computation filters (require computed values):
                Filter 1 — zero absolute difference     (§7.5.1)
                Filter 2 — below absolute threshold     (§7.5.2)
                Filter 3 — below percentage threshold   (§7.5.3)

        Any filter that fires returns a PairResult with threshold_met=False and
        pair_result=NO_DISCREPANCY. If no filter fires, the pair has a
        DISCREPANCY_DETECTED result and threshold_met=True.
        """
        source_a   = obs_a["source"]
        source_b   = obs_b["source"]
        obs_id_a   = obs_a["observation_id"]
        obs_id_b   = obs_b["observation_id"]
        price_a    = float(obs_a["normalized_price"])
        price_b    = float(obs_b["normalized_price"])
        pid        = _pair_id(source_a, source_b)

        # Threshold values to record in the pair result (None when inapplicable)
        abs_thresh_recorded = (
            absolute_threshold
            if threshold_method in (ThresholdMethod.ABSOLUTE.value, ThresholdMethod.BOTH.value)
            else None
        )
        pct_thresh_recorded = (
            percentage_threshold
            if threshold_method in (ThresholdMethod.PERCENTAGE.value, ThresholdMethod.BOTH.value)
            else None
        )

        # ------------------------------------------------------------------
        # Helper: build a skipped PairResult and emit the skip log.
        # Used by every filter branch below.
        # ------------------------------------------------------------------
        def _skipped(
            reason: str,
            noise_filter: NoiseFilter,
            abs_diff: float | None = None,
            pct_diff: float | None = None,
            lower_src: str | None = None,
            higher_src: str | None = None,
        ) -> PairResult:
            logger.debug(
                "discrepancy_worker_pair_skip",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "pair_id": pid,
                    "source_a": source_a,
                    "source_b": source_b,
                    "noise_filter": noise_filter.value,
                    "reason": reason,
                },
            )
            return PairResult(
                pair_id=pid,
                source_a=source_a,
                source_b=source_b,
                observation_id_a=obs_id_a,
                observation_id_b=obs_id_b,
                price_a=price_a,
                price_b=price_b,
                absolute_difference=abs_diff,
                percentage_difference=pct_diff,
                absolute_threshold_used=abs_thresh_recorded,
                percentage_threshold_used=pct_thresh_recorded,
                lower_price_source=lower_src,
                higher_price_source=higher_src,
                pair_result=DiscrepancyResultType.NO_DISCREPANCY.value,
                threshold_met=False,
                skip_reason=reason,
            )

        # ==============================================================
        # Pre-computation noise filters (4 → 5 → 6 → 7)
        # ==============================================================

        # Filter 4 — price not positive (§7.5.4, §9.4)
        # Must precede arithmetic to prevent zero-division in §7.2.
        if price_a <= 0 or price_b <= 0:
            return _skipped(
                reason=(
                    f"{NoiseFilter.PRICE_NOT_POSITIVE.value}: "
                    f"price_a={price_a}, price_b={price_b}. "
                    "Both must be strictly > 0."
                ),
                noise_filter=NoiseFilter.PRICE_NOT_POSITIVE,
            )

        # Filter 5 — same source (§7.5.5)
        # Observations from the same source must not be compared (§6.1).
        if source_a == source_b:
            return _skipped(
                reason=(
                    f"{NoiseFilter.SAME_SOURCE.value}: "
                    f"source_a={source_a!r} equals source_b. "
                    "Cross-source comparison requires distinct source identifiers."
                ),
                noise_filter=NoiseFilter.SAME_SOURCE,
            )

        # Filter 6 — unrelated product context (§7.5.6)
        # Stage 2 is responsible for ensuring context coherence.
        # Worker defends against this per contract §7.5.6.
        product_ref_a = obs_a.get("product_ref")
        product_ref_b = obs_b.get("product_ref")
        if (
            product_ref_a is not None
            and product_ref_b is not None
            and product_ref_a != product_ref_b
        ):
            return _skipped(
                reason=(
                    f"{NoiseFilter.UNRELATED_PRODUCT_CONTEXT.value}: "
                    f"product_ref_a={product_ref_a!r} != product_ref_b={product_ref_b!r}. "
                    "Context coherence is a Stage 2 responsibility."
                ),
                noise_filter=NoiseFilter.UNRELATED_PRODUCT_CONTEXT,
            )

        # Filter 7 — currency mismatch (§7.5.7)
        # Currency normalisation is a Stage 2 responsibility. If mismatched
        # currencies reach this worker the pair is ineligible.
        currency_a = obs_a.get("currency")
        currency_b = obs_b.get("currency")
        if (
            currency_a is not None
            and currency_b is not None
            and currency_a != currency_b
        ):
            return _skipped(
                reason=(
                    f"{NoiseFilter.CURRENCY_MISMATCH.value}: "
                    f"currency_a={currency_a!r} != currency_b={currency_b!r}. "
                    "Currency normalisation is a Stage 2 responsibility."
                ),
                noise_filter=NoiseFilter.CURRENCY_MISMATCH,
            )

        # ==============================================================
        # Arithmetic — Contract §7.1 and §7.2
        # Safe to compute: prices are > 0 and sources are distinct.
        # ==============================================================

        # §7.1 — absolute difference
        absolute_difference: float = abs(price_a - price_b)

        # §7.2 — percentage difference; denominator is the lesser price
        lesser_price: float = min(price_a, price_b)
        percentage_difference: float = (absolute_difference / lesser_price) * 100.0

        # §7.4 — directionality
        if price_a < price_b:
            lower_price_source: str = source_a
            higher_price_source: str = source_b
        elif price_b < price_a:
            lower_price_source = source_b
            higher_price_source = source_a
        else:
            # Equal prices — caught by filter 1 immediately below.
            # Assign symmetrically so the field is always populated.
            lower_price_source = source_a
            higher_price_source = source_a

        # ==============================================================
        # Post-computation noise filters (1 → 2 → 3), in documented order
        # ==============================================================

        # Filter 1 — zero absolute difference (§7.5.1)
        # §7.4: equal prices cannot meet any threshold > 0.
        if absolute_difference == 0.0:
            return _skipped(
                reason=(
                    f"{NoiseFilter.ZERO_DIFFERENCE.value}: "
                    f"absolute_difference=0.0 "
                    f"(price_a={price_a}, price_b={price_b})."
                ),
                noise_filter=NoiseFilter.ZERO_DIFFERENCE,
                abs_diff=absolute_difference,
                pct_diff=percentage_difference,
                lower_src=lower_price_source,
                higher_src=higher_price_source,
            )

        # Filter 2 — below absolute threshold (§7.5.2)
        # Applies when method is ABSOLUTE or BOTH.
        # For BOTH: a sub-threshold absolute difference disqualifies the pair
        # regardless of the percentage difference (§7.3 "both must be met").
        if threshold_method in (ThresholdMethod.ABSOLUTE.value, ThresholdMethod.BOTH.value):
            if absolute_difference < absolute_threshold:  # type: ignore[operator]
                return _skipped(
                    reason=(
                        f"{NoiseFilter.BELOW_ABSOLUTE_THRESHOLD.value}: "
                        f"absolute_difference={absolute_difference} < "
                        f"absolute_threshold={absolute_threshold}."
                    ),
                    noise_filter=NoiseFilter.BELOW_ABSOLUTE_THRESHOLD,
                    abs_diff=absolute_difference,
                    pct_diff=percentage_difference,
                    lower_src=lower_price_source,
                    higher_src=higher_price_source,
                )

        # Filter 3 — below percentage threshold (§7.5.3)
        # Applies when method is PERCENTAGE or BOTH.
        # For BOTH: a sub-threshold percentage disqualifies the pair even if the
        # absolute threshold was met (§7.3 "both must be met simultaneously").
        if threshold_method in (ThresholdMethod.PERCENTAGE.value, ThresholdMethod.BOTH.value):
            if percentage_difference < percentage_threshold:  # type: ignore[operator]
                return _skipped(
                    reason=(
                        f"{NoiseFilter.BELOW_PERCENTAGE_THRESHOLD.value}: "
                        f"percentage_difference={percentage_difference:.6f} < "
                        f"percentage_threshold={percentage_threshold}."
                    ),
                    noise_filter=NoiseFilter.BELOW_PERCENTAGE_THRESHOLD,
                    abs_diff=absolute_difference,
                    pct_diff=percentage_difference,
                    lower_src=lower_price_source,
                    higher_src=higher_price_source,
                )

        # ==============================================================
        # All filters cleared — discrepancy detected for this pair.
        # §7.3: threshold boundary semantics are >= (exactly equal meets it).
        # ==============================================================
        logger.debug(
            "discrepancy_worker_pair_evaluated",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "pair_id": pid,
                "source_a": source_a,
                "source_b": source_b,
                "price_a": price_a,
                "price_b": price_b,
                "absolute_difference": absolute_difference,
                "percentage_difference": percentage_difference,
                "absolute_threshold": absolute_threshold,
                "percentage_threshold": percentage_threshold,
                "pair_result": DiscrepancyResultType.DISCREPANCY_DETECTED.value,
            },
        )
        return PairResult(
            pair_id=pid,
            source_a=source_a,
            source_b=source_b,
            observation_id_a=obs_id_a,
            observation_id_b=obs_id_b,
            price_a=price_a,
            price_b=price_b,
            absolute_difference=absolute_difference,
            percentage_difference=percentage_difference,
            absolute_threshold_used=abs_thresh_recorded,
            percentage_threshold_used=pct_thresh_recorded,
            lower_price_source=lower_price_source,
            higher_price_source=higher_price_source,
            pair_result=DiscrepancyResultType.DISCREPANCY_DETECTED.value,
            threshold_met=True,
            skip_reason=None,
        )


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _pair_id(source_a: str, source_b: str) -> str:
    """
    Derive the canonical pair identifier from two source identifiers.

    ``source_a`` must already be the lexicographically lesser source;
    callers are responsible for canonical ordering before calling this.

    Contract §8.1 (pair_id field), §10.3.
    """
    return f"{source_a}::{source_b}"
