"""
Pipeline Runner — Opportunity Pipeline Orchestrator.

Contract: Contracts/PIPELINE_ORCHESTRATION_CONTRACT.md

Coordinates the fixed six-stage sequence:

    1. InputValidator        (Stage 1)
    2. DiscrepancyWorker     (Stage 2)
    3. ScoringWorker         (Stage 3)
    4. AlertDecisionWorker   (Stage 4)
    5. Final result assembly (Stage 5 — in-orchestrator)
    6. Audit / log emission  (Stage 6 — in-orchestrator)

Guarantees (Contract §3, §7, §14):
    - Sequential execution only (1 → 6), no stage skipping, no reordering.
    - Stops immediately on any terminal stop condition.
    - No business logic in the orchestrator — it routes, sequences, assembles.
    - Stage outputs are captured verbatim and passed forward unchanged (§9.4).
    - Deterministic: same input + same stage workers → same result.
    - Never reads the system clock. All timestamps flow from the pipeline
      input's ``freshness_reference_timestamp`` (§9.5).
    - Never makes external calls. All data required by each stage must be
      present in the pipeline input context (§5).
    - Stage 5 (assembly) and Stage 6 (audit) run on every execution (§6).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable

from aace_execution.persistence.db import connect as connect_postgres
from aace_execution.persistence.postgres_writer import PostgresWriter
from aace_execution.validators.input_validator import (
    InputValidator,
    ValidationResultType,
)
from aace_execution.workers.discrepancy_worker import (
    DiscrepancyWorker,
    DiscrepancyResultType,
)
from aace_execution.workers.scoring_worker import (
    ScoringWorker,
    ScoringResultType,
)
from aace_execution.workers.alert_decision_worker import (
    AlertDecisionWorker,
    AlertDecisionResultType,
    DuplicateCheckResult,
)

# Result classifications that produce an opportunities row (§7.2).
_OPPORTUNITY_RESULTS = frozenset({
    "OPPORTUNITY_DETECTED",
    "OPPORTUNITY_SCORED_NO_ALERT",
})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result classification — Contract §8
# ---------------------------------------------------------------------------

class PipelineResultType(str, Enum):
    """The seven and only seven final result classifications (Contract §8)."""
    OPPORTUNITY_DETECTED        = "OPPORTUNITY_DETECTED"
    OPPORTUNITY_SCORED_NO_ALERT = "OPPORTUNITY_SCORED_NO_ALERT"
    NO_OPPORTUNITY              = "NO_OPPORTUNITY"
    NO_OP                       = "NO_OP"
    VALIDATION_FAILURE          = "VALIDATION_FAILURE"
    PRECONDITION_FAILURE        = "PRECONDITION_FAILURE"
    PROCESSING_FAILURE          = "PROCESSING_FAILURE"


# ---------------------------------------------------------------------------
# Stage names used in logs, stop-reason records, and audit summaries
# ---------------------------------------------------------------------------

class StageName(str, Enum):
    INPUT_VALIDATION      = "INPUT_VALIDATION"
    DISCREPANCY_DETECTION = "DISCREPANCY_DETECTION"
    DUPLICATE_CHECK       = "DUPLICATE_CHECK"
    OPPORTUNITY_SCORING   = "OPPORTUNITY_SCORING"
    ALERT_DECISION        = "ALERT_DECISION"
    RESULT_ASSEMBLY       = "RESULT_ASSEMBLY"
    AUDIT_EMISSION        = "AUDIT_EMISSION"
    ORCHESTRATOR          = "ORCHESTRATOR"


# ---------------------------------------------------------------------------
# Output shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageOutcome:
    """One entry in the stage-level outcome summary emitted in Stage 6."""
    stage: str
    classification: str


@dataclass(frozen=True)
class AuditRecord:
    """Contract §13 — structured audit record emitted at Stage 6."""
    pipeline_execution_id: str
    product_id: str | None
    final_result: str
    result_timestamp: str
    stage_outcomes: tuple[StageOutcome, ...]
    failure_stage: str | None = None
    failure_reason: str | None = None
    retriable: bool | None = None
    suppression_reason: str | None = None
    stop_stage: str | None = None
    stop_reason: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    """
    The single classified return value of one pipeline execution
    (Contract §8). Callers receive this after Stage 6 completes.
    """
    result: str
    pipeline_execution_id: str
    product_id: str | None
    stage_outputs: dict
    audit: AuditRecord
    retriable: bool | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Duplicate-check resolver hook
# ---------------------------------------------------------------------------

DuplicateCheckResolver = Callable[[dict], str]
"""
Called before Stage 4 with the pipeline input context. Must return one of
'NO_PRIOR_ALERT' or 'PRIOR_ALERT_EXISTS'. Raising any exception is treated
as 'duplicate check resolution failure' per Contract §9.3 / §10.
"""


def _default_duplicate_check_from_context(context: dict) -> str:
    """
    Default resolver: read the pre-resolved value from the pipeline input
    context field ``duplicate_check_result``. The orchestrator does not
    perform the lookup itself (§13 forbids external calls); the upstream
    job layer supplies the pre-resolved value.
    """
    value = context.get("duplicate_check_result")
    if value not in (
        DuplicateCheckResult.NO_PRIOR_ALERT.value,
        DuplicateCheckResult.PRIOR_ALERT_EXISTS.value,
    ):
        raise ValueError(
            "duplicate_check_result must be NO_PRIOR_ALERT or PRIOR_ALERT_EXISTS; "
            f"received {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class PipelineRunner:
    """
    Stateless orchestrator for one pipeline execution per ``run()`` call.

    Dependencies are injected so the orchestrator itself defines no business
    logic (Contract §14). Every stage worker is fully owned by its contract.
    """

    def __init__(
        self,
        *,
        input_validator_factory: Callable[[dict], InputValidator] | None = None,
        discrepancy_worker: DiscrepancyWorker | None = None,
        scoring_worker: ScoringWorker | None = None,
        alert_decision_worker: AlertDecisionWorker | None = None,
        duplicate_check_resolver: DuplicateCheckResolver | None = None,
        audit_emitter: Callable[[AuditRecord], None] | None = None,
        postgres_writer: PostgresWriter | None = None,
    ) -> None:
        self._input_validator_factory = input_validator_factory
        self._discrepancy_worker = discrepancy_worker or DiscrepancyWorker()
        self._scoring_worker = scoring_worker or ScoringWorker()
        self._alert_decision_worker = (
            alert_decision_worker or AlertDecisionWorker()
        )
        self._duplicate_check_resolver = (
            duplicate_check_resolver or _default_duplicate_check_from_context
        )
        self._audit_emitter = audit_emitter
        self._postgres_writer = postgres_writer

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, pipeline_input: dict[str, Any]) -> PipelineResult:
        """
        Execute the full pipeline once.

        Returns exactly one :class:`PipelineResult`.  Never raises for
        business errors — classified failures surface as ``PROCESSING_FAILURE``
        (Contract §14: no swallowed exceptions, but orchestrator errors
        become classified results).
        """
        pipeline_execution_id = str(
            pipeline_input.get("pipeline_execution_id") or ""
        )
        product_id = pipeline_input.get("product_id")

        stage_outcomes: list[StageOutcome] = []
        stage_outputs: dict[str, Any] = {}
        stop_stage: str | None = None
        stop_reason: str | None = None

        logger.info(
            "pipeline_start",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "product_id": product_id,
                "observation_count": len(
                    pipeline_input.get("price_observations")
                    or pipeline_input.get("observations")
                    or []
                ),
                "freshness_reference_timestamp": str(
                    pipeline_input.get("freshness_reference_timestamp")
                ),
            },
        )

        try:
            # --- Stage 1 — Input Validation ------------------------------
            if not pipeline_execution_id:
                return self._halt_validation_failure(
                    pipeline_execution_id="<missing>",
                    product_id=product_id,
                    reason="pipeline_execution_id is required",
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            logger.info(
                "stage_start",
                extra={
                    "stage": StageName.INPUT_VALIDATION.value,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )
            validator = self._build_input_validator(pipeline_input)
            validation_result = validator.validate(pipeline_input)
            stage_outputs["input_validation"] = validation_result
            validation_classification = getattr(
                validation_result, "result", "UNKNOWN"
            )
            stage_outcomes.append(
                StageOutcome(
                    stage=StageName.INPUT_VALIDATION.value,
                    classification=validation_classification,
                )
            )
            logger.info(
                "stage_complete",
                extra={
                    "stage": StageName.INPUT_VALIDATION.value,
                    "classification": validation_classification,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )

            if validation_classification == ValidationResultType.INVALID.value:
                stop_stage = StageName.INPUT_VALIDATION.value
                stop_reason = ValidationResultType.INVALID.value
                return self._assemble_and_emit(
                    final=PipelineResultType.VALIDATION_FAILURE.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    stop_stage=stop_stage,
                    stop_reason=stop_reason,
                )

            if validation_classification == ValidationResultType.PRECONDITION_FAILURE.value:
                stop_stage = StageName.INPUT_VALIDATION.value
                stop_reason = ValidationResultType.PRECONDITION_FAILURE.value
                return self._assemble_and_emit(
                    final=PipelineResultType.PRECONDITION_FAILURE.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    stop_stage=stop_stage,
                    stop_reason=stop_reason,
                    retriable=getattr(validation_result, "retriable", None),
                )

            if validation_classification != ValidationResultType.VALID.value:
                # Validator returned an unexpected classification — orchestrator error.
                return self._halt_orchestrator_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    reason=(
                        "Stage 1 returned unexpected classification "
                        f"{validation_classification!r}"
                    ),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            # --- Stage 2 — Discrepancy Detection -------------------------
            logger.info(
                "stage_start",
                extra={
                    "stage": StageName.DISCREPANCY_DETECTION.value,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )
            discrepancy_input = self._build_discrepancy_input(pipeline_input)
            discrepancy_result = self._discrepancy_worker.evaluate(
                discrepancy_input
            )
            stage_outputs["discrepancy_detection"] = discrepancy_result
            discrepancy_classification = getattr(
                discrepancy_result, "result", "UNKNOWN"
            )
            stage_outcomes.append(
                StageOutcome(
                    stage=StageName.DISCREPANCY_DETECTION.value,
                    classification=discrepancy_classification,
                )
            )
            logger.info(
                "stage_complete",
                extra={
                    "stage": StageName.DISCREPANCY_DETECTION.value,
                    "classification": discrepancy_classification,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )

            if discrepancy_classification == DiscrepancyResultType.NO_DISCREPANCY.value:
                stop_stage = StageName.DISCREPANCY_DETECTION.value
                stop_reason = DiscrepancyResultType.NO_DISCREPANCY.value
                return self._assemble_and_emit(
                    final=PipelineResultType.NO_OPPORTUNITY.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    stop_stage=stop_stage,
                    stop_reason=stop_reason,
                )

            if discrepancy_classification == "NO_OP":
                stop_stage = StageName.DISCREPANCY_DETECTION.value
                stop_reason = "NO_OP"
                return self._assemble_and_emit(
                    final=PipelineResultType.NO_OP.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    stop_stage=stop_stage,
                    stop_reason=stop_reason,
                )

            if discrepancy_classification == DiscrepancyResultType.PROCESSING_FAILURE.value:
                return self._halt_processing_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    failure_stage=StageName.DISCREPANCY_DETECTION.value,
                    failure_reason=getattr(
                        discrepancy_result, "failure_reason", "UNKNOWN"
                    ),
                    retriable=getattr(discrepancy_result, "retriable", True),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            if discrepancy_classification != DiscrepancyResultType.DISCREPANCY_DETECTED.value:
                return self._halt_orchestrator_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    reason=(
                        "Stage 2 returned unexpected classification "
                        f"{discrepancy_classification!r}"
                    ),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            # --- Stage 3 — Opportunity Scoring ---------------------------
            logger.info(
                "stage_start",
                extra={
                    "stage": StageName.OPPORTUNITY_SCORING.value,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )
            scoring_input = self._build_scoring_input(
                pipeline_input, discrepancy_result
            )
            scoring_result = self._scoring_worker.evaluate(scoring_input)
            stage_outputs["opportunity_scoring"] = scoring_result
            scoring_classification = getattr(
                scoring_result, "result", "UNKNOWN"
            )
            stage_outcomes.append(
                StageOutcome(
                    stage=StageName.OPPORTUNITY_SCORING.value,
                    classification=scoring_classification,
                )
            )
            logger.info(
                "stage_complete",
                extra={
                    "stage": StageName.OPPORTUNITY_SCORING.value,
                    "classification": scoring_classification,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )

            if scoring_classification == ScoringResultType.NO_SCORE.value:
                stop_stage = StageName.OPPORTUNITY_SCORING.value
                stop_reason = ScoringResultType.NO_SCORE.value
                return self._assemble_and_emit(
                    final=PipelineResultType.NO_OPPORTUNITY.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    stop_stage=stop_stage,
                    stop_reason=stop_reason,
                )

            if scoring_classification == ScoringResultType.PROCESSING_FAILURE.value:
                return self._halt_processing_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    failure_stage=StageName.OPPORTUNITY_SCORING.value,
                    failure_reason=getattr(
                        scoring_result, "failure_reason", "UNKNOWN"
                    ),
                    retriable=getattr(scoring_result, "retriable", True),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            if scoring_classification != ScoringResultType.SCORED_OPPORTUNITY.value:
                return self._halt_orchestrator_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    reason=(
                        "Stage 3 returned unexpected classification "
                        f"{scoring_classification!r}"
                    ),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            # --- Duplicate check resolution (between Stage 3 and 4) ------
            logger.info(
                "stage_start",
                extra={
                    "stage": StageName.DUPLICATE_CHECK.value,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )
            try:
                duplicate_check_value = self._duplicate_check_resolver(
                    pipeline_input
                )
                if duplicate_check_value not in (
                    DuplicateCheckResult.NO_PRIOR_ALERT.value,
                    DuplicateCheckResult.PRIOR_ALERT_EXISTS.value,
                ):
                    raise ValueError(
                        f"Invalid duplicate_check_result: {duplicate_check_value!r}"
                    )
            except Exception as exc:  # §9.3: resolution failure → PROCESSING_FAILURE
                return self._halt_processing_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    failure_stage=StageName.DUPLICATE_CHECK.value,
                    failure_reason=f"DUPLICATE_CHECK_RESOLUTION_FAILED: {exc}",
                    retriable=True,
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            stage_outputs["duplicate_check_result"] = duplicate_check_value
            stage_outcomes.append(
                StageOutcome(
                    stage=StageName.DUPLICATE_CHECK.value,
                    classification=duplicate_check_value,
                )
            )
            logger.info(
                "duplicate_check_resolved",
                extra={
                    "pipeline_execution_id": pipeline_execution_id,
                    "duplicate_check_result": duplicate_check_value,
                },
            )

            # --- Stage 4 — Alert Decision --------------------------------
            logger.info(
                "stage_start",
                extra={
                    "stage": StageName.ALERT_DECISION.value,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )
            decision_input = self._build_alert_input(
                pipeline_input, scoring_result, duplicate_check_value
            )
            alert_result = self._alert_decision_worker.evaluate(decision_input)
            stage_outputs["alert_decision"] = alert_result
            alert_classification = getattr(alert_result, "result", "UNKNOWN")
            stage_outcomes.append(
                StageOutcome(
                    stage=StageName.ALERT_DECISION.value,
                    classification=alert_classification,
                )
            )
            logger.info(
                "stage_complete",
                extra={
                    "stage": StageName.ALERT_DECISION.value,
                    "classification": alert_classification,
                    "pipeline_execution_id": pipeline_execution_id,
                },
            )

            if alert_classification == AlertDecisionResultType.PROCESSING_FAILURE.value:
                return self._halt_processing_failure(
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    failure_stage=StageName.ALERT_DECISION.value,
                    failure_reason=getattr(
                        alert_result, "failure_reason", "UNKNOWN"
                    ),
                    retriable=getattr(alert_result, "retriable", True),
                    stage_outcomes=stage_outcomes,
                    stage_outputs=stage_outputs,
                )

            if alert_classification == AlertDecisionResultType.ALERT_ELIGIBLE.value:
                return self._assemble_and_emit(
                    final=PipelineResultType.OPPORTUNITY_DETECTED.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                )

            if alert_classification == AlertDecisionResultType.NO_ALERT.value:
                return self._assemble_and_emit(
                    final=PipelineResultType.OPPORTUNITY_SCORED_NO_ALERT.value,
                    pipeline_execution_id=pipeline_execution_id,
                    product_id=product_id,
                    stage_outputs=stage_outputs,
                    stage_outcomes=stage_outcomes,
                    suppression_reason=getattr(
                        alert_result, "suppression_reason", None
                    ),
                )

            return self._halt_orchestrator_failure(
                pipeline_execution_id=pipeline_execution_id,
                product_id=product_id,
                reason=(
                    "Stage 4 returned unexpected classification "
                    f"{alert_classification!r}"
                ),
                stage_outcomes=stage_outcomes,
                stage_outputs=stage_outputs,
            )

        except Exception as exc:  # Contract §7 Rule 8 / §14: orchestrator error
            logger.exception(
                "pipeline_orchestrator_error",
                extra={"pipeline_execution_id": pipeline_execution_id},
            )
            return self._halt_orchestrator_failure(
                pipeline_execution_id=pipeline_execution_id,
                product_id=product_id,
                reason=f"{type(exc).__name__}: {exc}",
                stage_outcomes=stage_outcomes,
                stage_outputs=stage_outputs,
            )

    # ------------------------------------------------------------------
    # Stage-input construction (pure pass-through of pipeline-context fields)
    # ------------------------------------------------------------------

    def _build_input_validator(self, pipeline_input: dict) -> InputValidator:
        """Construct the Stage 1 validator. A factory may be injected."""
        if self._input_validator_factory is not None:
            return self._input_validator_factory(pipeline_input)
        # No sensible default exists: ValidationContext requires fields that
        # only the caller can supply.  Require injection.
        raise ValueError(
            "input_validator_factory must be provided to PipelineRunner"
        )

    def _build_discrepancy_input(self, pipeline_input: dict) -> dict:
        """Build Stage 2 input — routing only; no transformation (§9.2, §9.4)."""
        out: dict[str, Any] = {
            "pipeline_execution_id": pipeline_input.get("pipeline_execution_id"),
            "product_id": pipeline_input.get("product_id"),
            "product_name": pipeline_input.get("product_name"),
            "evaluation_reference_timestamp": pipeline_input.get(
                "freshness_reference_timestamp"
            ),
            "observations": (
                pipeline_input.get("observations")
                or pipeline_input.get("price_observations")
            ),
            "discrepancy_rule_set": pipeline_input.get("discrepancy_rule_set"),
        }
        # Pass through any additional context fields the worker may need
        # without modification (§9.4).
        for key in (
            "listings",
            "product_context",
            "currency",
            "normalized_observations",
        ):
            if key in pipeline_input:
                out[key] = pipeline_input[key]
        return out

    def _build_scoring_input(
        self, pipeline_input: dict, discrepancy_result: Any
    ) -> dict:
        """
        Build Stage 3 input — routes the Stage 2 output forward verbatim
        alongside the scoring configuration from the pipeline context (§9.2).
        """
        pair_results = getattr(discrepancy_result, "pair_results", ()) or ()
        first_pair = pair_results[0] if pair_results else None

        observations = (
            pipeline_input.get("observations")
            or pipeline_input.get("price_observations")
            or []
        )
        obs_ts_by_id = {
            o.get("observation_id"): o.get("observed_at")
            for o in observations
            if isinstance(o, dict)
        }

        return {
            "pipeline_execution_id": pipeline_input.get(
                "pipeline_execution_id"
            ),
            "pair_id": getattr(first_pair, "pair_id", None),
            "product_id": pipeline_input.get("product_id"),
            "discrepancy_result": getattr(
                discrepancy_result, "result", None
            ),
            "source_a": getattr(first_pair, "source_a", None),
            "source_b": getattr(first_pair, "source_b", None),
            "price_a": getattr(first_pair, "price_a", None),
            "price_b": getattr(first_pair, "price_b", None),
            "absolute_difference": getattr(
                first_pair, "absolute_difference", None
            ),
            "percentage_difference": getattr(
                first_pair, "percentage_difference", None
            ),
            "threshold_method": getattr(
                discrepancy_result, "threshold_method", None
            ),
            "lower_price_source": getattr(
                first_pair, "lower_price_source", None
            ),
            "higher_price_source": getattr(
                first_pair, "higher_price_source", None
            ),
            "observation_timestamp_a": obs_ts_by_id.get(
                getattr(first_pair, "observation_id_a", None)
            ),
            "observation_timestamp_b": obs_ts_by_id.get(
                getattr(first_pair, "observation_id_b", None)
            ),
            "freshness_reference_timestamp": pipeline_input.get(
                "freshness_reference_timestamp"
            ),
            "scoring_timestamp": pipeline_input.get(
                "freshness_reference_timestamp"
            ),
            "scoring_factors": _scoring_cfg(
                pipeline_input, "scoring_factors"
            ),
            "score_range": _scoring_cfg(pipeline_input, "score_range"),
            "normalization_method": _scoring_cfg(
                pipeline_input, "normalization_method"
            ),
            "tie_break_order": _scoring_cfg(
                pipeline_input, "tie_break_order"
            ),
        }

    def _build_alert_input(
        self,
        pipeline_input: dict,
        scoring_result: Any,
        duplicate_check_value: str,
    ) -> dict:
        """Build Stage 4 input — pass-through routing only (§9.2, §9.4)."""
        return {
            "pipeline_execution_id": pipeline_input.get(
                "pipeline_execution_id"
            ),
            "score_result_id": getattr(scoring_result, "score_result_id", None),
            "product_id": pipeline_input.get("product_id"),
            "pair_id": getattr(scoring_result, "pair_id", None),
            "scoring_result": getattr(scoring_result, "result", None),
            "score": getattr(scoring_result, "score", None),
            "score_range": _scoring_cfg(pipeline_input, "score_range"),
            "alert_threshold": pipeline_input.get("alert_threshold"),
            "opportunity_status": pipeline_input.get("opportunity_status"),
            "eligible_opportunity_statuses": pipeline_input.get(
                "eligible_opportunity_statuses"
            ),
            "duplicate_check_result": duplicate_check_value,
            "notification_type": pipeline_input.get("notification_type"),
            "decision_reference_timestamp": pipeline_input.get(
                "freshness_reference_timestamp"
            ),
            "discrepancy_reference": getattr(
                scoring_result, "discrepancy_reference", None
            ),
            "factors_applied": list(
                getattr(scoring_result, "factors_applied", ()) or ()
            ),
        }

    # ------------------------------------------------------------------
    # Stage 5 + Stage 6 — assembly and emission
    # ------------------------------------------------------------------

    def _assemble_and_emit(
        self,
        *,
        final: str,
        pipeline_execution_id: str,
        product_id: Any,
        stage_outputs: dict,
        stage_outcomes: list[StageOutcome],
        stop_stage: str | None = None,
        stop_reason: str | None = None,
        retriable: bool | None = None,
        failure_stage: str | None = None,
        failure_reason: str | None = None,
        suppression_reason: str | None = None,
    ) -> PipelineResult:
        """Stages 5 + 6 — assemble the classified result and emit the audit."""
        result_timestamp = str(
            stage_outputs.get("_freshness_reference_timestamp")
            or _extract_reference_timestamp(stage_outputs)
            or ""
        )

        audit = AuditRecord(
            pipeline_execution_id=pipeline_execution_id,
            product_id=product_id,
            final_result=final,
            result_timestamp=result_timestamp,
            stage_outcomes=tuple(stage_outcomes),
            failure_stage=failure_stage,
            failure_reason=failure_reason,
            retriable=retriable,
            suppression_reason=suppression_reason,
            stop_stage=stop_stage,
            stop_reason=stop_reason,
        )
        stage_outcomes.append(
            StageOutcome(
                stage=StageName.RESULT_ASSEMBLY.value,
                classification=final,
            )
        )

        # Stage 6 — audit emission MUST run for every execution (§6, §13).
        self._emit_audit(audit, pipeline_execution_id=pipeline_execution_id)

        logger.info(
            "pipeline_end",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "final_result": final,
            },
        )

        # Persistence — runs after Stage 6, never alters the pipeline result.
        self._persist_if_enabled(
            final=final,
            audit=audit,
            stage_outputs=stage_outputs,
        )

        return PipelineResult(
            result=final,
            pipeline_execution_id=pipeline_execution_id,
            product_id=product_id,
            stage_outputs=dict(stage_outputs),
            audit=audit,
            retriable=retriable,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )

    def _emit_audit(
        self, audit: AuditRecord, *, pipeline_execution_id: str
    ) -> None:
        """
        Stage 6: emit structured log + audit record. Failure here must surface
        (§6, §13) — the orchestrator does not suppress audit failures.
        """
        logger.info(
            "audit_record",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "final_result": audit.final_result,
                "stage_outcomes": [
                    {"stage": s.stage, "classification": s.classification}
                    for s in audit.stage_outcomes
                ],
                "failure_stage": audit.failure_stage,
                "failure_reason": audit.failure_reason,
                "retriable": audit.retriable,
                "suppression_reason": audit.suppression_reason,
                "stop_stage": audit.stop_stage,
                "stop_reason": audit.stop_reason,
            },
        )
        if self._audit_emitter is not None:
            self._audit_emitter(audit)

    # ------------------------------------------------------------------
    # Persistence (post-Stage-6, never alters the pipeline result)
    # ------------------------------------------------------------------

    def _persist_if_enabled(
        self,
        *,
        final: str,
        audit: AuditRecord,
        stage_outputs: dict,
    ) -> None:
        """Translate the assembled result + audit into persistence payloads and
        invoke PostgresWriter.persist_execution exactly once. The pipeline result
        returned to the caller is unaffected by the persistence outcome."""
        if self._postgres_writer is None:
            return

        try:
            pipeline_result_params = _build_pipeline_result_params(final, audit)
            opportunity_params = (
                _build_opportunity_params(final, audit, stage_outputs)
                if final in _OPPORTUNITY_RESULTS
                else None
            )
            alert_decision_params = _build_alert_decision_params(
                final, audit, stage_outputs
            )
            audit_record_params = _build_audit_record_params(
                final, audit, stage_outputs
            )

            outcome = self._postgres_writer.persist_execution(
                pipeline_result_params=pipeline_result_params,
                opportunity_params=opportunity_params,
                alert_decision_params=alert_decision_params,
                audit_record_params=audit_record_params,
            )
            logger.info(
                "persistence_outcome",
                extra={
                    "pipeline_execution_id": audit.pipeline_execution_id,
                    "status": outcome.status.value,
                    "pipeline_result_write": outcome.pipeline_result_write.status.value,
                    "opportunity_write": (
                        outcome.opportunity_write.status.value
                        if outcome.opportunity_write is not None
                        else None
                    ),
                    "alert_decision_write": (
                        outcome.alert_decision_write.status.value
                        if outcome.alert_decision_write is not None
                        else None
                    ),
                    "audit_record_write": (
                        outcome.audit_record_write.status.value
                        if outcome.audit_record_write is not None
                        else None
                    ),
                },
            )
        except Exception:
            logger.exception(
                "persistence_invocation_error",
                extra={"pipeline_execution_id": audit.pipeline_execution_id},
            )

    # ------------------------------------------------------------------
    # Halt helpers
    # ------------------------------------------------------------------

    def _halt_validation_failure(
        self,
        *,
        pipeline_execution_id: str,
        product_id: Any,
        reason: str,
        stage_outcomes: list[StageOutcome],
        stage_outputs: dict,
    ) -> PipelineResult:
        stage_outcomes.append(
            StageOutcome(
                stage=StageName.INPUT_VALIDATION.value,
                classification=ValidationResultType.INVALID.value,
            )
        )
        return self._assemble_and_emit(
            final=PipelineResultType.VALIDATION_FAILURE.value,
            pipeline_execution_id=pipeline_execution_id,
            product_id=product_id,
            stage_outputs=stage_outputs,
            stage_outcomes=stage_outcomes,
            stop_stage=StageName.INPUT_VALIDATION.value,
            stop_reason=reason,
        )

    def _halt_processing_failure(
        self,
        *,
        pipeline_execution_id: str,
        product_id: Any,
        failure_stage: str,
        failure_reason: str,
        retriable: bool,
        stage_outcomes: list[StageOutcome],
        stage_outputs: dict,
    ) -> PipelineResult:
        logger.warning(
            "pipeline_processing_failure",
            extra={
                "pipeline_execution_id": pipeline_execution_id,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "retriable": retriable,
            },
        )
        return self._assemble_and_emit(
            final=PipelineResultType.PROCESSING_FAILURE.value,
            pipeline_execution_id=pipeline_execution_id,
            product_id=product_id,
            stage_outputs=stage_outputs,
            stage_outcomes=stage_outcomes,
            stop_stage=failure_stage,
            stop_reason=failure_reason,
            retriable=retriable,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )

    def _halt_orchestrator_failure(
        self,
        *,
        pipeline_execution_id: str,
        product_id: Any,
        reason: str,
        stage_outcomes: list[StageOutcome],
        stage_outputs: dict,
    ) -> PipelineResult:
        """Contract §7 Rule 8: orchestrator internal error → PROCESSING_FAILURE."""
        return self._halt_processing_failure(
            pipeline_execution_id=pipeline_execution_id,
            product_id=product_id,
            failure_stage=StageName.ORCHESTRATOR.value,
            failure_reason=reason,
            retriable=False,
            stage_outcomes=stage_outcomes,
            stage_outputs=stage_outputs,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scoring_cfg(pipeline_input: dict, key: str) -> Any:
    """Read a scoring-config field from a ``scoring_factor_set`` wrapper if
    present, else from the top-level pipeline input. Pure routing (§9.2)."""
    wrapper = pipeline_input.get("scoring_factor_set")
    if isinstance(wrapper, dict) and key in wrapper:
        return wrapper[key]
    return pipeline_input.get(key)


def _audit_stage_outcome_summary(audit: AuditRecord) -> str:
    """JSON-encode the audit's stage outcomes for JSONB persistence columns."""
    return json.dumps(
        [
            {"stage": s.stage, "classification": s.classification}
            for s in audit.stage_outcomes
        ]
    )


def _build_pipeline_result_params(final: str, audit: AuditRecord) -> dict[str, Any]:
    return {
        "pipeline_execution_id": audit.pipeline_execution_id,
        "product_id": audit.product_id,
        "result_classification": final,
        "stage_reached": (
            audit.stage_outcomes[-1].stage if audit.stage_outcomes else ""
        ),
        "result_timestamp": audit.result_timestamp,
        "stage_outcome_summary": _audit_stage_outcome_summary(audit),
        "retry_eligible": audit.retriable,
        "failure_stage": audit.failure_stage,
        "failure_reason": audit.failure_reason,
    }


def _build_opportunity_params(
    final: str, audit: AuditRecord, stage_outputs: dict
) -> dict[str, Any] | None:
    """Translate Stage 2/3/4 captured outputs into an opportunities row payload.
    Returns None if required upstream data is missing — caller skips the write."""
    discrepancy = stage_outputs.get("discrepancy_detection")
    scoring = stage_outputs.get("opportunity_scoring")
    if discrepancy is None or scoring is None:
        return None

    pair_results = getattr(discrepancy, "pair_results", ()) or ()
    if not pair_results:
        return None
    first_pair = pair_results[0]

    alert = stage_outputs.get("alert_decision")
    alert_decision_value = (
        getattr(alert, "result", None) if alert is not None else None
    ) or "NO_ALERT"
    alert_decision_id = (
        getattr(alert, "alert_decision_id", None) if alert is not None else None
    ) or ""
    suppression_reason = (
        getattr(alert, "suppression_reason", None) if alert is not None else None
    )

    return {
        "pipeline_execution_id": audit.pipeline_execution_id,
        "product_id": audit.product_id,
        "pair_id": getattr(first_pair, "pair_id", None),
        "result_classification": final,
        "discrepancy_rule_id": getattr(discrepancy, "discrepancy_rule_id", None)
        or getattr(discrepancy, "rule_id", None),
        "discrepancy_source_a": getattr(first_pair, "source_a", None),
        "discrepancy_source_b": getattr(first_pair, "source_b", None),
        "price_a": getattr(first_pair, "price_a", None),
        "price_b": getattr(first_pair, "price_b", None),
        "absolute_difference": getattr(first_pair, "absolute_difference", None),
        "percentage_difference": getattr(first_pair, "percentage_difference", None),
        "score": getattr(scoring, "score", None),
        "score_result_id": getattr(scoring, "score_result_id", None),
        "scoring_factors_applied": json.dumps(
            [asdict(f) for f in (getattr(scoring, "factors_applied", ()) or ())]
        ),
        "score_range": json.dumps(getattr(scoring, "score_range", None) or {}),
        "alert_decision": alert_decision_value,
        "alert_decision_id": alert_decision_id,
        "suppression_reason": suppression_reason,
        "opportunity_timestamp": audit.result_timestamp,
    }


def _build_alert_decision_params(
    final: str, audit: AuditRecord, stage_outputs: dict
) -> dict[str, Any] | None:
    """Translate Stage 4 output into an alert_decisions row payload.
    Returns None when no Stage 4 alert data exists for this execution."""
    alert = stage_outputs.get("alert_decision")
    if alert is None:
        return None
    alert_decision_id = getattr(alert, "alert_decision_id", None)
    if not alert_decision_id:
        return None

    scoring = stage_outputs.get("opportunity_scoring")
    duplicate_check_value = stage_outputs.get("duplicate_check_result")
    if not duplicate_check_value:
        return None

    return {
        "pipeline_execution_id": audit.pipeline_execution_id,
        "notification_type": getattr(alert, "notification_type", None) or "",
        "alert_decision_id": alert_decision_id,
        "product_id": audit.product_id,
        "pair_id": getattr(alert, "pair_id", None)
        or (getattr(scoring, "pair_id", None) if scoring is not None else None),
        "score": getattr(alert, "score", None)
        or (getattr(scoring, "score", None) if scoring is not None else None),
        "alert_threshold": getattr(alert, "alert_threshold", None),
        "threshold_met": getattr(alert, "threshold_met", None),
        "decision_result": getattr(alert, "result", None),
        "suppression_reason": getattr(alert, "suppression_reason", None),
        "decision_basis": json.dumps(
            [asdict(e) for e in (getattr(alert, "decision_basis", None) or ())]
        ),
        "duplicate_check_result": duplicate_check_value,
        "decision_reference_timestamp": audit.result_timestamp,
    }


def _build_audit_record_params(
    final: str, audit: AuditRecord, stage_outputs: dict
) -> dict[str, Any]:
    scoring = stage_outputs.get("opportunity_scoring")
    discrepancy = stage_outputs.get("discrepancy_detection")
    alert = stage_outputs.get("alert_decision")

    return {
        "pipeline_execution_id": audit.pipeline_execution_id,
        "product_id": audit.product_id,
        "result_classification": final,
        "result_timestamp": audit.result_timestamp,
        "stage_outcome_summary": _audit_stage_outcome_summary(audit),
        "discrepancy_rule_applied": (
            getattr(discrepancy, "discrepancy_rule_id", None)
            or getattr(discrepancy, "rule_id", None)
            if discrepancy is not None
            else None
        ),
        "score": getattr(scoring, "score", None) if scoring is not None else None,
        "scoring_factor_summary": (
            json.dumps(
                [asdict(f) for f in (getattr(scoring, "factors_applied", ()) or ())]
            )
            if scoring is not None
            else None
        ),
        "alert_decision": (
            getattr(alert, "result", None) if alert is not None else None
        ),
        "failure_stage": audit.failure_stage,
        "failure_reason": audit.failure_reason,
        "early_exit_stage": audit.stop_stage if audit.failure_stage is None else None,
        "early_exit_reason": audit.stop_reason if audit.failure_stage is None else None,
    }


def _extract_reference_timestamp(stage_outputs: dict) -> str | None:
    """Pull the freshness reference timestamp off any captured stage output."""
    for key in (
        "input_validation",
        "discrepancy_detection",
        "opportunity_scoring",
        "alert_decision",
    ):
        item = stage_outputs.get(key)
        if item is None:
            continue
        ts = (
            getattr(item, "evaluation_reference_timestamp", None)
            or getattr(item, "freshness_reference_timestamp", None)
            or getattr(item, "decision_reference_timestamp", None)
            or getattr(item, "validated_at", None)
        )
        if ts is not None:
            return str(ts)
    return None
