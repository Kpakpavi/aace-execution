"""
Alert Decision Worker — Stage 6 of the AACE Opportunity Pipeline.

Contract: Contracts/ALERT_DECISION_CONTRACT.md

Consumes a valid SCORED_OPPORTUNITY result and a pre-resolved
duplicate_check_result, and produces a single deterministic decision:
ALERT_ELIGIBLE, NO_ALERT, or PROCESSING_FAILURE.

Determinism guarantees (Contract §10):
    - Same input → same decision.
    - No system clock is consulted.
    - No randomness.
    - No external calls.
    - No AI model invocation.
    - No alert threshold, status list, or policy is hardcoded here — all come
      from the loaded configuration.
    - Rule evaluation order is fixed: threshold → status → duplicate (§7.5).
    - Threshold semantics are inclusive: `score >= alert_threshold` (§7.1).

What this worker does NOT do (Contract §13):
    - Send, queue, or schedule notifications.
    - Persist alert records.
    - Score opportunities.
    - Fetch or enrich data from external sources.
    - Perform the duplicate lookup itself.
    - Redefine alert thresholds, eligible statuses, or notification policy.
    - Use the system clock.
    - Apply engagement heuristics or behavioral signals.
    - Operate on more than one scored opportunity per invocation.
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

class AlertDecisionResultType(str, Enum):
    """The three and only three result states — Contract §8."""
    ALERT_ELIGIBLE     = "ALERT_ELIGIBLE"
    NO_ALERT           = "NO_ALERT"
    PROCESSING_FAILURE = "PROCESSING_FAILURE"


# ---------------------------------------------------------------------------
# Suppression reasons — Contract §7.1, §7.2, §7.3, §8.2
# ---------------------------------------------------------------------------

class SuppressionReason(str, Enum):
    """The exhaustive set of NO_ALERT suppression reasons."""
    SCORE_BELOW_THRESHOLD        = "SCORE_BELOW_THRESHOLD"
    INELIGIBLE_OPPORTUNITY_STATUS = "INELIGIBLE_OPPORTUNITY_STATUS"
    DUPLICATE_ALERT_SUPPRESSED   = "DUPLICATE_ALERT_SUPPRESSED"


# ---------------------------------------------------------------------------
# Failure reasons — Contract §8.3, §9
# ---------------------------------------------------------------------------

class FailureReason(str, Enum):
    """The exhaustive set of PROCESSING_FAILURE reason classifiers."""
    PRECONDITION_VIOLATION           = "PRECONDITION_VIOLATION"
    INVALID_SCORED_OPPORTUNITY_INPUT = "INVALID_SCORED_OPPORTUNITY_INPUT"
    MISSING_ALERT_CONFIGURATION      = "MISSING_ALERT_CONFIGURATION"
    INVALID_THRESHOLD_CONFIGURATION  = "INVALID_THRESHOLD_CONFIGURATION"
    UNEXPECTED_RUNTIME_ERROR         = "UNEXPECTED_RUNTIME_ERROR"


# ---------------------------------------------------------------------------
# Sub-stage identifiers — Contract §8.3 failure_stage
# ---------------------------------------------------------------------------

class FailureStage(str, Enum):
    """Sub-stage within this worker where the failure occurred."""
    INPUT_PARSE                = "INPUT_PARSE"
    PRECONDITION_CHECK         = "PRECONDITION_CHECK"
    THRESHOLD_EVALUATION       = "THRESHOLD_EVALUATION"
    STATUS_EVALUATION          = "STATUS_EVALUATION"
    DUPLICATE_CHECK_APPLICATION = "DUPLICATE_CHECK_APPLICATION"
    DECISION_ASSEMBLY          = "DECISION_ASSEMBLY"


# ---------------------------------------------------------------------------
# Rule names — Contract §7.5 (evaluation order)
# ---------------------------------------------------------------------------

class RuleName(str, Enum):
    """Fixed rule identifiers, in evaluation order (Contract §7.5)."""
    SCORE_THRESHOLD       = "SCORE_THRESHOLD"
    ELIGIBLE_STATUS       = "ELIGIBLE_STATUS"
    DUPLICATE_PREVENTION  = "DUPLICATE_PREVENTION"


class RuleResult(str, Enum):
    """Per-rule evaluation result in decision_basis entries."""
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Duplicate-check values — Contract §4, §7.3
# ---------------------------------------------------------------------------

class DuplicateCheckResult(str, Enum):
    """Recognized pre-resolved duplicate-check values."""
    NO_PRIOR_ALERT     = "NO_PRIOR_ALERT"
    PRIOR_ALERT_EXISTS = "PRIOR_ALERT_EXISTS"


# ---------------------------------------------------------------------------
# Per-rule decision_basis entry — Contract §8.1, §8.2
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionBasisEntry:
    """
    One entry in the ordered decision_basis list (§8.1 table).
    `reason` is populated for FAILED rules, None for PASSED.
    """
    rule_name: str
    rule_result: str
    reason: str | None


# ---------------------------------------------------------------------------
# Top-level result dataclasses — Contract §8.1, §8.2, §8.3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlertEligibleResult:
    """Contract §8.1 — all three rules passed."""
    result: str                                    # ALERT_ELIGIBLE
    pipeline_execution_id: str
    alert_decision_id: str
    score_result_id: str
    product_id: str
    pair_id: str
    score: float
    alert_threshold: float
    threshold_met: bool                            # always True
    opportunity_status: str
    eligible_statuses_used: tuple[str, ...]
    duplicate_check_result: str                    # always NO_PRIOR_ALERT
    notification_type: str
    decision_basis: tuple[DecisionBasisEntry, ...]
    discrepancy_reference: dict
    scoring_factor_summary: tuple[dict, ...]
    decision_reference_timestamp: str


@dataclass(frozen=True)
class NoAlertResult:
    """Contract §8.2 — at least one rule failed. Not an error."""
    result: str                                    # NO_ALERT
    pipeline_execution_id: str
    alert_decision_id: str
    score_result_id: str
    product_id: str
    pair_id: str
    score: float
    alert_threshold: float
    threshold_met: bool
    suppression_reason: str
    decision_basis: tuple[DecisionBasisEntry, ...]
    notification_type: str
    decision_reference_timestamp: str


@dataclass(frozen=True)
class ProcessingFailureResult:
    """Contract §8.3 — structural, configuration, or runtime failure."""
    result: str                                    # PROCESSING_FAILURE
    pipeline_execution_id: str | None
    score_result_id: str | None
    product_id: str | None
    pair_id: str | None
    failure_reason: str
    failure_stage: str
    retriable: bool
    error_context: str


# Union type for return annotations
AlertDecisionResult = (
    AlertEligibleResult | NoAlertResult | ProcessingFailureResult
)


# ---------------------------------------------------------------------------
# Internal classified error
# ---------------------------------------------------------------------------

class _AlertDecisionError(Exception):
    """Classified error raised by validators; caught by evaluate()."""

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

class AlertDecisionWorker:
    """
    Decides alert eligibility for one scored opportunity.

    The worker is stateless. Call ``evaluate()`` once per opportunity.
    Same input always returns the same decision (Contract §10.1).

    Usage::

        worker = AlertDecisionWorker()
        result = worker.evaluate(decision_input)
    """

    def evaluate(
        self, decision_input: dict[str, Any]
    ) -> AlertDecisionResult:
        """
        Evaluate one alert decision input. Returns exactly one of:
            ALERT_ELIGIBLE, NO_ALERT, or PROCESSING_FAILURE.

        Contract §3, §7, §8.
        """
        # Defensive identifier extraction so every failure path populates
        # the identifiers on the failure result (§8.3).
        pipeline_execution_id: str | None = None
        score_result_id: str | None = None
        product_id: str | None = None
        pair_id: str | None = None

        try:
            # -----------------------------------------------------------
            # 1. Input parse — must be a dict.
            # -----------------------------------------------------------
            if not isinstance(decision_input, dict):
                raise _AlertDecisionError(
                    reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                    stage=FailureStage.INPUT_PARSE,
                    context=(
                        f"Decision input must be a dict. "
                        f"Received {type(decision_input).__name__}."
                    ),
                    retriable=False,
                )

            pipeline_execution_id = decision_input.get("pipeline_execution_id")
            score_result_id       = decision_input.get("score_result_id")
            product_id            = decision_input.get("product_id")
            pair_id               = decision_input.get("pair_id")

            logger.info(
                "alert_decision_worker_start",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "score_result_id": score_result_id,
                    "product_id": product_id,
                    "score": decision_input.get("score"),
                    "alert_threshold": decision_input.get("alert_threshold"),
                    "notification_type": decision_input.get(
                        "notification_type"
                    ),
                },
            )

            # -----------------------------------------------------------
            # 2. Precondition check — Contract §5.
            # -----------------------------------------------------------
            self._check_preconditions(decision_input)
            logger.debug(
                "alert_decision_worker_preconditions_passed",
                extra={"pipeline_execution_id": pipeline_execution_id},
            )

            # -----------------------------------------------------------
            # 3. Bind validated fields.
            # -----------------------------------------------------------
            pipeline_execution_id = decision_input["pipeline_execution_id"]
            score_result_id       = decision_input["score_result_id"]
            product_id            = decision_input["product_id"]
            pair_id               = decision_input["pair_id"]

            score: float           = float(decision_input["score"])
            alert_threshold: float = float(decision_input["alert_threshold"])
            opportunity_status: str = decision_input["opportunity_status"]
            eligible_statuses: list[str] = list(
                decision_input["eligible_opportunity_statuses"]
            )
            duplicate_check_result: str = decision_input[
                "duplicate_check_result"
            ]
            notification_type: str = decision_input["notification_type"]
            decision_reference_timestamp_raw = decision_input[
                "decision_reference_timestamp"
            ]
            discrepancy_reference: dict = decision_input.get(
                "discrepancy_reference"
            ) or {}
            scoring_factor_summary: list = list(
                decision_input.get("factors_applied") or []
            )

            alert_decision_id = _derive_alert_decision_id(
                pipeline_execution_id=pipeline_execution_id,
                notification_type=notification_type,
            )

            # -----------------------------------------------------------
            # 4. Rule evaluation in fixed order (§7.5).
            #    Stop at the first failed rule — subsequent rules are NOT
            #    evaluated and are NOT added to decision_basis (§7.5).
            # -----------------------------------------------------------
            decision_basis: list[DecisionBasisEntry] = []

            # ---- Rule 1 — Score threshold (§7.1) ---------------------
            threshold_met: bool = score >= alert_threshold
            if threshold_met:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.SCORE_THRESHOLD.value,
                    rule_result=RuleResult.PASSED.value,
                    reason=None,
                ))
                logger.info(
                    "alert_decision_threshold_evaluation",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "score": score,
                        "alert_threshold": alert_threshold,
                        "rule_result": RuleResult.PASSED.value,
                    },
                )
            else:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.SCORE_THRESHOLD.value,
                    rule_result=RuleResult.FAILED.value,
                    reason=SuppressionReason.SCORE_BELOW_THRESHOLD.value,
                ))
                logger.info(
                    "alert_decision_threshold_evaluation",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "score": score,
                        "alert_threshold": alert_threshold,
                        "rule_result": RuleResult.FAILED.value,
                    },
                )
                return self._build_no_alert(
                    pipeline_execution_id=pipeline_execution_id,
                    alert_decision_id=alert_decision_id,
                    score_result_id=score_result_id,
                    product_id=product_id,
                    pair_id=pair_id,
                    score=score,
                    alert_threshold=alert_threshold,
                    threshold_met=False,
                    suppression_reason=SuppressionReason.SCORE_BELOW_THRESHOLD,
                    decision_basis=decision_basis,
                    notification_type=notification_type,
                    decision_reference_timestamp=str(
                        decision_reference_timestamp_raw
                    ),
                )

            # ---- Rule 2 — Eligible status (§7.2) ----------------------
            status_eligible: bool = opportunity_status in eligible_statuses
            if status_eligible:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.ELIGIBLE_STATUS.value,
                    rule_result=RuleResult.PASSED.value,
                    reason=None,
                ))
                logger.info(
                    "alert_decision_status_evaluation",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "opportunity_status": opportunity_status,
                        "eligible_opportunity_statuses": eligible_statuses,
                        "rule_result": RuleResult.PASSED.value,
                    },
                )
            else:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.ELIGIBLE_STATUS.value,
                    rule_result=RuleResult.FAILED.value,
                    reason=SuppressionReason.INELIGIBLE_OPPORTUNITY_STATUS.value,
                ))
                logger.info(
                    "alert_decision_status_evaluation",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "opportunity_status": opportunity_status,
                        "eligible_opportunity_statuses": eligible_statuses,
                        "rule_result": RuleResult.FAILED.value,
                    },
                )
                return self._build_no_alert(
                    pipeline_execution_id=pipeline_execution_id,
                    alert_decision_id=alert_decision_id,
                    score_result_id=score_result_id,
                    product_id=product_id,
                    pair_id=pair_id,
                    score=score,
                    alert_threshold=alert_threshold,
                    threshold_met=True,
                    suppression_reason=(
                        SuppressionReason.INELIGIBLE_OPPORTUNITY_STATUS
                    ),
                    decision_basis=decision_basis,
                    notification_type=notification_type,
                    decision_reference_timestamp=str(
                        decision_reference_timestamp_raw
                    ),
                )

            # ---- Rule 3 — Duplicate prevention (§7.3) -----------------
            no_prior_alert: bool = (
                duplicate_check_result
                == DuplicateCheckResult.NO_PRIOR_ALERT.value
            )
            if no_prior_alert:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.DUPLICATE_PREVENTION.value,
                    rule_result=RuleResult.PASSED.value,
                    reason=None,
                ))
                logger.info(
                    "alert_decision_duplicate_check",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "duplicate_check_result": duplicate_check_result,
                        "rule_result": RuleResult.PASSED.value,
                    },
                )
            else:
                decision_basis.append(DecisionBasisEntry(
                    rule_name=RuleName.DUPLICATE_PREVENTION.value,
                    rule_result=RuleResult.FAILED.value,
                    reason=SuppressionReason.DUPLICATE_ALERT_SUPPRESSED.value,
                ))
                logger.info(
                    "alert_decision_duplicate_check",
                    extra={
                        "pipeline_execution_id": pipeline_execution_id,
                        "duplicate_check_result": duplicate_check_result,
                        "rule_result": RuleResult.FAILED.value,
                    },
                )
                return self._build_no_alert(
                    pipeline_execution_id=pipeline_execution_id,
                    alert_decision_id=alert_decision_id,
                    score_result_id=score_result_id,
                    product_id=product_id,
                    pair_id=pair_id,
                    score=score,
                    alert_threshold=alert_threshold,
                    threshold_met=True,
                    suppression_reason=(
                        SuppressionReason.DUPLICATE_ALERT_SUPPRESSED
                    ),
                    decision_basis=decision_basis,
                    notification_type=notification_type,
                    decision_reference_timestamp=str(
                        decision_reference_timestamp_raw
                    ),
                )

            # -----------------------------------------------------------
            # 5. All three rules passed → ALERT_ELIGIBLE (§7.4, §8.1).
            # -----------------------------------------------------------
            result = AlertEligibleResult(
                result=AlertDecisionResultType.ALERT_ELIGIBLE.value,
                pipeline_execution_id=pipeline_execution_id,
                alert_decision_id=alert_decision_id,
                score_result_id=score_result_id,
                product_id=product_id,
                pair_id=pair_id,
                score=score,
                alert_threshold=alert_threshold,
                threshold_met=True,
                opportunity_status=opportunity_status,
                eligible_statuses_used=tuple(eligible_statuses),
                duplicate_check_result=(
                    DuplicateCheckResult.NO_PRIOR_ALERT.value
                ),
                notification_type=notification_type,
                decision_basis=tuple(decision_basis),
                discrepancy_reference=discrepancy_reference,
                scoring_factor_summary=tuple(scoring_factor_summary),
                decision_reference_timestamp=str(
                    decision_reference_timestamp_raw
                ),
            )

            logger.info(
                "alert_decision_worker_end",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "result": result.result,
                },
            )
            return result

        except _AlertDecisionError as err:
            logger.warning(
                "alert_decision_worker_failure",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "score_result_id": score_result_id,
                    "product_id": product_id,
                    "pair_id": pair_id,
                    "failure_reason": err.reason.value,
                    "failure_stage": err.stage.value,
                    "retriable": err.retriable,
                    "error_context": err.context,
                },
            )
            return ProcessingFailureResult(
                result=AlertDecisionResultType.PROCESSING_FAILURE.value,
                pipeline_execution_id=pipeline_execution_id,
                score_result_id=score_result_id,
                product_id=product_id,
                pair_id=pair_id,
                failure_reason=err.reason.value,
                failure_stage=err.stage.value,
                retriable=err.retriable,
                error_context=err.context,
            )

        except Exception as exc:
            # Contract §9.4 — Unexpected runtime error.
            reason = (
                f"Unexpected runtime error in ALERT_DECISION_WORKER: "
                f"{type(exc).__name__}: {exc}"
            )
            logger.error(
                "alert_decision_worker_unexpected_error",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "score_result_id": score_result_id,
                    "product_id": product_id,
                    "pair_id": pair_id,
                    "error_context": reason,
                },
                exc_info=True,
            )
            return ProcessingFailureResult(
                result=AlertDecisionResultType.PROCESSING_FAILURE.value,
                pipeline_execution_id=pipeline_execution_id,
                score_result_id=score_result_id,
                product_id=product_id,
                pair_id=pair_id,
                failure_reason=FailureReason.UNEXPECTED_RUNTIME_ERROR.value,
                failure_stage=FailureStage.DECISION_ASSEMBLY.value,
                retriable=True,  # §9.4: treat as potentially transient.
                error_context=reason,
            )

    # ------------------------------------------------------------------
    # Precondition checks — Contract §5
    # ------------------------------------------------------------------

    def _check_preconditions(self, ctx: dict) -> None:
        """
        Verify the ten preconditions from Contract §5. Raises
        _AlertDecisionError with the correct failure reason on any violation.
        """
        # --- §5.9 pipeline_execution_id present ------------------------
        pid = ctx.get("pipeline_execution_id")
        if not pid or not isinstance(pid, str):
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context="Precondition §5.9: 'pipeline_execution_id' absent or empty.",
                retriable=False,
            )

        # --- §5.10 score_result_id present -----------------------------
        srid = ctx.get("score_result_id")
        if not srid or not isinstance(srid, str):
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context="Precondition §5.10: 'score_result_id' absent or empty.",
                retriable=False,
            )

        # --- Required identifier fields (§4) ---------------------------
        for required in ("product_id", "pair_id"):
            val = ctx.get(required)
            if not val or not isinstance(val, str):
                raise _AlertDecisionError(
                    reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Required field '{required}' is absent, null, or not "
                        f"a non-empty string."
                    ),
                    retriable=False,
                )

        # --- §5.1 scoring_result must be SCORED_OPPORTUNITY ------------
        scoring_result = ctx.get("scoring_result")
        if scoring_result != "SCORED_OPPORTUNITY":
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.1: 'scoring_result' must be "
                    f"'SCORED_OPPORTUNITY'. Received {scoring_result!r}."
                ),
                retriable=False,
            )

        # --- §5.2 score is finite and within score_range ---------------
        score = ctx.get("score")
        if (
            score is None
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
        ):
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.2: 'score' is absent or not numeric "
                    f"(not bool). Received {score!r}."
                ),
                retriable=False,
            )
        score_f = float(score)
        if not math.isfinite(score_f):
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.2: 'score' must be finite. "
                    f"Received {score}."
                ),
                retriable=False,
            )

        score_range = ctx.get("score_range")
        if not isinstance(score_range, dict):
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.2: 'score_range' must be an object with "
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
                raise _AlertDecisionError(
                    reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.2: 'score_range.{name}' must be a "
                        f"finite number. Received {val!r}."
                    ),
                    retriable=False,
                )
        s_min_f = float(s_min)
        s_max_f = float(s_max)
        if s_min_f >= s_max_f:
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.2: 'score_range.min' ({s_min}) must be "
                    f"strictly less than 'score_range.max' ({s_max})."
                ),
                retriable=False,
            )
        if score_f < s_min_f or score_f > s_max_f:
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.2: 'score' ({score_f}) is outside the "
                    f"configured score_range [{s_min_f}, {s_max_f}]."
                ),
                retriable=False,
            )

        # --- §5.3 alert_threshold present, numeric, within score_range -
        if "alert_threshold" not in ctx or ctx.get("alert_threshold") is None:
            raise _AlertDecisionError(
                reason=FailureReason.MISSING_ALERT_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.3: 'alert_threshold' is absent or null."
                ),
                retriable=False,
            )
        alert_threshold = ctx["alert_threshold"]
        if (
            isinstance(alert_threshold, bool)
            or not isinstance(alert_threshold, (int, float))
        ):
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_THRESHOLD_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.3: 'alert_threshold' must be numeric "
                    f"(not bool). Received {alert_threshold!r}."
                ),
                retriable=False,
            )
        at_f = float(alert_threshold)
        if not math.isfinite(at_f):
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_THRESHOLD_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.3: 'alert_threshold' must be finite. "
                    f"Received {alert_threshold}."
                ),
                retriable=False,
            )
        if at_f < s_min_f or at_f > s_max_f:
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_THRESHOLD_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.3: 'alert_threshold' ({at_f}) must be "
                    f"within score_range [{s_min_f}, {s_max_f}]."
                ),
                retriable=False,
            )

        # --- §5.4 eligible_opportunity_statuses non-empty list ---------
        eligible_statuses = ctx.get("eligible_opportunity_statuses")
        if (
            eligible_statuses is None
            or not isinstance(eligible_statuses, list)
            or len(eligible_statuses) == 0
        ):
            raise _AlertDecisionError(
                reason=FailureReason.MISSING_ALERT_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.4: 'eligible_opportunity_statuses' must "
                    "be a non-empty list."
                ),
                retriable=False,
            )
        for i, s in enumerate(eligible_statuses):
            if not s or not isinstance(s, str):
                raise _AlertDecisionError(
                    reason=FailureReason.MISSING_ALERT_CONFIGURATION,
                    stage=FailureStage.PRECONDITION_CHECK,
                    context=(
                        f"Precondition §5.4: eligible_opportunity_statuses[{i}] "
                        f"must be a non-empty string."
                    ),
                    retriable=False,
                )

        # --- §5.5 opportunity_status present and non-null --------------
        opportunity_status = ctx.get("opportunity_status")
        if not opportunity_status or not isinstance(opportunity_status, str):
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.5: 'opportunity_status' is absent, null, "
                    "or not a non-empty string."
                ),
                retriable=False,
            )

        # --- §5.6 duplicate_check_result present and recognized --------
        duplicate_check_result = ctx.get("duplicate_check_result")
        valid_duplicate_values = {v.value for v in DuplicateCheckResult}
        if duplicate_check_result not in valid_duplicate_values:
            raise _AlertDecisionError(
                reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    f"Precondition §5.6: 'duplicate_check_result' must be one "
                    f"of {sorted(valid_duplicate_values)}. "
                    f"Received {duplicate_check_result!r}."
                ),
                retriable=False,
            )

        # --- §5.7 notification_type present and non-empty --------------
        notification_type = ctx.get("notification_type")
        if not notification_type or not isinstance(notification_type, str):
            raise _AlertDecisionError(
                reason=FailureReason.MISSING_ALERT_CONFIGURATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.7: 'notification_type' is absent, null, "
                    "or not a non-empty string."
                ),
                retriable=False,
            )

        # --- §5.8 decision_reference_timestamp valid ISO 8601 ----------
        decision_ts_raw = ctx.get("decision_reference_timestamp")
        if decision_ts_raw is None:
            raise _AlertDecisionError(
                reason=FailureReason.PRECONDITION_VIOLATION,
                stage=FailureStage.PRECONDITION_CHECK,
                context=(
                    "Precondition §5.8: 'decision_reference_timestamp' is absent."
                ),
                retriable=False,
            )
        _parse_iso8601(
            decision_ts_raw,
            field_name="decision_reference_timestamp",
        )

    # ------------------------------------------------------------------
    # NO_ALERT builder — used at every early return point
    # ------------------------------------------------------------------

    def _build_no_alert(
        self,
        *,
        pipeline_execution_id: str,
        alert_decision_id: str,
        score_result_id: str,
        product_id: str,
        pair_id: str,
        score: float,
        alert_threshold: float,
        threshold_met: bool,
        suppression_reason: SuppressionReason,
        decision_basis: list[DecisionBasisEntry],
        notification_type: str,
        decision_reference_timestamp: str,
    ) -> NoAlertResult:
        result = NoAlertResult(
            result=AlertDecisionResultType.NO_ALERT.value,
            pipeline_execution_id=pipeline_execution_id,
            alert_decision_id=alert_decision_id,
            score_result_id=score_result_id,
            product_id=product_id,
            pair_id=pair_id,
            score=score,
            alert_threshold=alert_threshold,
            threshold_met=threshold_met,
            suppression_reason=suppression_reason.value,
            decision_basis=tuple(decision_basis),
            notification_type=notification_type,
            decision_reference_timestamp=decision_reference_timestamp,
        )
        logger.info(
            "alert_decision_worker_end",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "result": result.result,
                "suppression_reason": result.suppression_reason,
            },
        )
        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_iso8601(value: Any, *, field_name: str) -> datetime:
    """
    Parse an ISO 8601 timestamp string or datetime into a datetime instance.

    Raises _AlertDecisionError (PRECONDITION_VIOLATION) if the value is
    missing or malformed.
    """
    if value is None:
        raise _AlertDecisionError(
            reason=FailureReason.PRECONDITION_VIOLATION,
            stage=FailureStage.PRECONDITION_CHECK,
            context=f"Required timestamp field '{field_name}' is absent.",
            retriable=False,
        )

    if isinstance(value, datetime):
        return value

    if not isinstance(value, str):
        raise _AlertDecisionError(
            reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
            stage=FailureStage.PRECONDITION_CHECK,
            context=(
                f"Timestamp field '{field_name}' must be an ISO 8601 string "
                f"or a datetime. Received {type(value).__name__}."
            ),
            retriable=False,
        )

    try:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _AlertDecisionError(
            reason=FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT,
            stage=FailureStage.PRECONDITION_CHECK,
            context=(
                f"Timestamp field '{field_name}' is not a valid ISO 8601 "
                f"string: {value!r} ({exc})."
            ),
            retriable=False,
        ) from exc


def _derive_alert_decision_id(
    *, pipeline_execution_id: str, notification_type: str
) -> str:
    """
    Derive a deterministic `alert_decision_id` from pipeline_execution_id
    and notification_type — Contract §8.1, §10.11, §11.2.
    """
    return f"alert::{pipeline_execution_id}::{notification_type}"
