"""
Unit tests for PipelineRunner.

Contract: Contracts/PIPELINE_ORCHESTRATION_CONTRACT.md

Covers:
  §8  — Final result paths (all seven classifications)
  §6  — Sequential stage ordering
  §10 — Stop conditions halt later stages
  §9  — Stage output passing between stages
  §13 — Stage 6 audit/log emission on every outcome
  §7  — Orchestrator PROCESSING_FAILURE uses failure_stage=ORCHESTRATOR

Tests never read the system clock and make no external calls. Stage
workers are replaced with simple fakes. Validator results use the real
classes because the orchestrator uses isinstance() on them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest # type: ignore

from src.aace_execution.pipeline.pipeline_runner import (
    AuditRecord,
    PipelineResult,
    PipelineResultType,
    PipelineRunner,
    StageName,
)
from src.aace_execution.validators.input_validator import (
    InvalidResult,
    PreconditionFailureResult as ValidatorPreconditionFailure,
    ValidResult,
    ValidationResultType,
)
from src.aace_execution.workers.discrepancy_worker import DiscrepancyResultType
from src.aace_execution.workers.scoring_worker import ScoringResultType
from src.aace_execution.workers.alert_decision_worker import (
    AlertDecisionResultType,
    DuplicateCheckResult,
)


# ---------------------------------------------------------------------------
# Fixed, deterministic values
# ---------------------------------------------------------------------------

FIXED_TS = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_TS_STR = "2026-04-15T12:00:00+00:00"
PIPELINE_ID = "pipeline-exec-0001"
PRODUCT_ID = "product-0001"
PAIR_ID = "pair-0001"
SCORE_RESULT_ID = "score-0001"


# ---------------------------------------------------------------------------
# Fakes for stage workers
# ---------------------------------------------------------------------------

class _CallRecorder:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[Any] = []


class FakeValidator:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[dict] = []

    def validate(self, pipeline_input: dict) -> Any:
        self.calls.append(pipeline_input)
        return self._result


class FakeDiscrepancyWorker(_CallRecorder):
    def evaluate(self, input_dict: dict) -> Any:
        self.calls.append(input_dict)
        return self._result


class FakeScoringWorker(_CallRecorder):
    def evaluate(self, input_dict: dict) -> Any:
        self.calls.append(input_dict)
        return self._result


class FakeAlertDecisionWorker(_CallRecorder):
    def evaluate(self, input_dict: dict) -> Any:
        self.calls.append(input_dict)
        return self._result


class SequenceRecorder:
    """Shared recorder — every fake worker appends its stage name."""

    def __init__(self) -> None:
        self.sequence: list[str] = []

    def wrap(self, name: str, fake: Any) -> Any:
        seq = self.sequence
        original_evaluate = getattr(fake, "evaluate", None)
        original_validate = getattr(fake, "validate", None)

        if original_evaluate is not None:
            def evaluate(input_dict, _orig=original_evaluate, _name=name):
                seq.append(_name)
                return _orig(input_dict)
            fake.evaluate = evaluate  # type: ignore[attr-defined]
        if original_validate is not None:
            def validate(pipeline_input, _orig=original_validate, _name=name):
                seq.append(_name)
                return _orig(pipeline_input)
            fake.validate = validate  # type: ignore[attr-defined]
        return fake


# ---------------------------------------------------------------------------
# Builders for worker results
# ---------------------------------------------------------------------------

def make_valid_result() -> ValidResult:
    return ValidResult(
        result=ValidationResultType.VALID.value,
        validated_at=FIXED_TS,
        input_identity=PIPELINE_ID,
        observation_count=2,
        source_count=2,
    )


def make_invalid_result() -> InvalidResult:
    return InvalidResult(
        result=ValidationResultType.INVALID.value,
        validated_at=FIXED_TS,
        input_identity=PIPELINE_ID,
        failure_category="CATEGORY_1_MISSING_REQUIRED_FIELDS",
        errors=(),
    )


def make_precondition_failure(retriable: bool = True) -> ValidatorPreconditionFailure:
    return ValidatorPreconditionFailure(
        result=ValidationResultType.PRECONDITION_FAILURE.value,
        validated_at=FIXED_TS,
        input_identity=PIPELINE_ID,
        precondition_failed="STALE_TIMESTAMPS",
        reason="observation too old",
        retriable=retriable,
    )


def make_discrepancy_detected() -> SimpleNamespace:
    pair = SimpleNamespace(
        pair_id=PAIR_ID,
        source_a="A",
        source_b="B",
        price_a=100.0,
        price_b=120.0,
        absolute_difference=20.0,
        percentage_difference=0.2,
        lower_price_source="A",
        higher_price_source="B",
    )
    return SimpleNamespace(
        result=DiscrepancyResultType.DISCREPANCY_DETECTED.value,
        product_id=PRODUCT_ID,
        pipeline_execution_id=PIPELINE_ID,
        evaluation_reference_timestamp=FIXED_TS_STR,
        threshold_method="absolute",
        pair_results=(pair,),
    )


def make_no_discrepancy() -> SimpleNamespace:
    return SimpleNamespace(
        result=DiscrepancyResultType.NO_DISCREPANCY.value,
        pipeline_execution_id=PIPELINE_ID,
        evaluation_reference_timestamp=FIXED_TS_STR,
    )


def make_discrepancy_no_op() -> SimpleNamespace:
    return SimpleNamespace(
        result="NO_OP",
        pipeline_execution_id=PIPELINE_ID,
        evaluation_reference_timestamp=FIXED_TS_STR,
    )


def make_discrepancy_processing_failure() -> SimpleNamespace:
    return SimpleNamespace(
        result=DiscrepancyResultType.PROCESSING_FAILURE.value,
        pipeline_execution_id=PIPELINE_ID,
        evaluation_reference_timestamp=FIXED_TS_STR,
        failure_stage="DISCREPANCY_WORKER",
        failure_reason="BOOM",
        retriable=True,
    )


def make_scored_opportunity() -> SimpleNamespace:
    return SimpleNamespace(
        result=ScoringResultType.SCORED_OPPORTUNITY.value,
        pipeline_execution_id=PIPELINE_ID,
        score_result_id=SCORE_RESULT_ID,
        pair_id=PAIR_ID,
        score=0.9,
        discrepancy_reference={"rule_id": "r1"},
        factors_applied=(),
        freshness_reference_timestamp=FIXED_TS_STR,
    )


def make_no_score() -> SimpleNamespace:
    return SimpleNamespace(
        result=ScoringResultType.NO_SCORE.value,
        pipeline_execution_id=PIPELINE_ID,
        pair_id=PAIR_ID,
        ineligibility_reason="below_min",
        freshness_reference_timestamp=FIXED_TS_STR,
    )


def make_scoring_processing_failure() -> SimpleNamespace:
    return SimpleNamespace(
        result=ScoringResultType.PROCESSING_FAILURE.value,
        pipeline_execution_id=PIPELINE_ID,
        failure_reason="BAD_CONFIG",
        retriable=False,
    )


def make_alert_eligible() -> SimpleNamespace:
    return SimpleNamespace(
        result=AlertDecisionResultType.ALERT_ELIGIBLE.value,
        pipeline_execution_id=PIPELINE_ID,
        alert_decision_id="alert-0001",
    )


def make_no_alert(reason: str = "DUPLICATE_SUPPRESSED") -> SimpleNamespace:
    return SimpleNamespace(
        result=AlertDecisionResultType.NO_ALERT.value,
        pipeline_execution_id=PIPELINE_ID,
        suppression_reason=reason,
    )


def make_alert_processing_failure() -> SimpleNamespace:
    return SimpleNamespace(
        result=AlertDecisionResultType.PROCESSING_FAILURE.value,
        pipeline_execution_id=PIPELINE_ID,
        failure_reason="ALERT_BOOM",
        retriable=True,
    )


# ---------------------------------------------------------------------------
# Pipeline input
# ---------------------------------------------------------------------------

def make_pipeline_input(**overrides: Any) -> dict:
    base = {
        "pipeline_execution_id": PIPELINE_ID,
        "product_id": PRODUCT_ID,
        "freshness_reference_timestamp": FIXED_TS_STR,
        "price_observations": [
            {"source_id": "A", "price": 100.0, "observation_timestamp": FIXED_TS_STR},
            {"source_id": "B", "price": 120.0, "observation_timestamp": FIXED_TS_STR},
        ],
        "discrepancy_rule_set": {"rule_id": "r1"},
        "scoring_factor_set": {"factors": []},
        "score_range": {"min": 0.0, "max": 1.0},
        "normalization_method": None,
        "tie_break_order": (),
        "alert_threshold": 0.5,
        "eligible_opportunity_statuses": ("OPEN",),
        "opportunity_status": "OPEN",
        "notification_type": "EMAIL",
        "duplicate_check_result": DuplicateCheckResult.NO_PRIOR_ALERT.value,
        "freshness_window_seconds": 3600,
        "max_retry_count": 3,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Runner assembly helper
# ---------------------------------------------------------------------------

def build_runner(
    *,
    validator_result: Any,
    discrepancy_result: Any = None,
    scoring_result: Any = None,
    alert_result: Any = None,
    duplicate_check_resolver=None,
    audit_sink: list[AuditRecord] | None = None,
    sequence: SequenceRecorder | None = None,
) -> tuple[PipelineRunner, dict[str, Any]]:
    validator = FakeValidator(validator_result)
    discrepancy = FakeDiscrepancyWorker(discrepancy_result)
    scoring = FakeScoringWorker(scoring_result)
    alert = FakeAlertDecisionWorker(alert_result)

    if sequence is not None:
        sequence.wrap(StageName.INPUT_VALIDATION.value, validator)
        sequence.wrap(StageName.DISCREPANCY_DETECTION.value, discrepancy)
        sequence.wrap(StageName.OPPORTUNITY_SCORING.value, scoring)
        sequence.wrap(StageName.ALERT_DECISION.value, alert)

    def audit_emitter(rec: AuditRecord) -> None:
        if audit_sink is not None:
            audit_sink.append(rec)

    runner = PipelineRunner(
        input_validator_factory=lambda _pi: validator,
        discrepancy_worker=discrepancy,
        scoring_worker=scoring,
        alert_decision_worker=alert,
        duplicate_check_resolver=duplicate_check_resolver,
        audit_emitter=audit_emitter,
    )
    return runner, {
        "validator": validator,
        "discrepancy": discrepancy,
        "scoring": scoring,
        "alert": alert,
    }


# ---------------------------------------------------------------------------
# §8 — Final result paths
# ---------------------------------------------------------------------------

class TestFinalResultPaths:
    def test_opportunity_detected(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert isinstance(result, PipelineResult)
        assert result.result == PipelineResultType.OPPORTUNITY_DETECTED.value
        assert result.pipeline_execution_id == PIPELINE_ID
        assert result.product_id == PRODUCT_ID
        assert result.failure_stage is None
        assert sink and sink[0].final_result == PipelineResultType.OPPORTUNITY_DETECTED.value

    def test_opportunity_scored_no_alert(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_no_alert(reason="BELOW_THRESHOLD"),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.OPPORTUNITY_SCORED_NO_ALERT.value
        assert sink[0].suppression_reason == "BELOW_THRESHOLD"
        # NO_ALERT is NOT a stop condition — no stop_stage recorded.
        assert sink[0].stop_stage is None
        assert sink[0].failure_stage is None

    def test_no_opportunity_from_stage2_no_discrepancy(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_no_discrepancy(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.NO_OPPORTUNITY.value
        assert sink[0].stop_stage == StageName.DISCREPANCY_DETECTION.value
        assert sink[0].stop_reason == DiscrepancyResultType.NO_DISCREPANCY.value

    def test_no_opportunity_from_stage3_no_score(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_no_score(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.NO_OPPORTUNITY.value
        assert sink[0].stop_stage == StageName.OPPORTUNITY_SCORING.value

    def test_no_op(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_no_op(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.NO_OP.value
        assert sink[0].stop_stage == StageName.DISCREPANCY_DETECTION.value
        assert sink[0].stop_reason == "NO_OP"

    def test_validation_failure_invalid(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_invalid_result(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.VALIDATION_FAILURE.value
        assert sink[0].stop_stage == StageName.INPUT_VALIDATION.value

    def test_validation_failure_missing_pipeline_execution_id(self):
        sink: list[AuditRecord] = []
        runner, fakes = build_runner(
            validator_result=make_valid_result(),
            audit_sink=sink,
        )
        pi = make_pipeline_input(pipeline_execution_id="")
        result = runner.run(pi)
        assert result.result == PipelineResultType.VALIDATION_FAILURE.value
        # The validator (Stage 1) must NOT be invoked — missing ID halts pre-Stage-1.
        assert fakes["validator"].calls == []
        assert sink and sink[0].final_result == PipelineResultType.VALIDATION_FAILURE.value

    def test_precondition_failure(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_precondition_failure(retriable=True),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PRECONDITION_FAILURE.value
        assert result.retriable is True
        assert sink[0].retriable is True
        assert sink[0].stop_stage == StageName.INPUT_VALIDATION.value

    def test_processing_failure_stage2(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_processing_failure(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.DISCREPANCY_DETECTION.value
        assert result.retriable is True

    def test_processing_failure_stage3(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scoring_processing_failure(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.OPPORTUNITY_SCORING.value
        assert result.retriable is False

    def test_processing_failure_stage4(self):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_processing_failure(),
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.ALERT_DECISION.value

    def test_processing_failure_duplicate_check_resolution(self):
        sink: list[AuditRecord] = []

        def bad_resolver(_ctx: dict) -> str:
            raise RuntimeError("resolver unavailable")

        runner, fakes = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            duplicate_check_resolver=bad_resolver,
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.DUPLICATE_CHECK.value
        # Stage 4 must NOT be invoked after duplicate-check failure.
        assert fakes["alert"].calls == []


# ---------------------------------------------------------------------------
# §6 / §7 — Sequential stage ordering
# ---------------------------------------------------------------------------

class TestSequentialOrdering:
    def test_full_happy_path_executes_stages_in_order(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
            StageName.OPPORTUNITY_SCORING.value,
            StageName.ALERT_DECISION.value,
        ]


# ---------------------------------------------------------------------------
# §10 — Stop conditions halt later stages
# ---------------------------------------------------------------------------

class TestStopConditionsHaltLaterStages:
    def test_invalid_stops_before_stage2(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_invalid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [StageName.INPUT_VALIDATION.value]

    def test_precondition_stops_before_stage2(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_precondition_failure(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [StageName.INPUT_VALIDATION.value]

    def test_no_discrepancy_stops_before_stage3(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_no_discrepancy(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
        ]

    def test_no_op_stops_before_stage3(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_no_op(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
        ]

    def test_stage2_processing_failure_stops_before_stage3(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_processing_failure(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
        ]

    def test_no_score_stops_before_stage4(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_no_score(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
            StageName.OPPORTUNITY_SCORING.value,
        ]

    def test_stage3_processing_failure_stops_before_stage4(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scoring_processing_failure(),
            alert_result=make_alert_eligible(),
            sequence=seq,
        )
        runner.run(make_pipeline_input())
        assert seq.sequence == [
            StageName.INPUT_VALIDATION.value,
            StageName.DISCREPANCY_DETECTION.value,
            StageName.OPPORTUNITY_SCORING.value,
        ]

    def test_no_alert_is_not_a_stop_condition(self):
        seq = SequenceRecorder()
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_no_alert(),
            sequence=seq,
        )
        result = runner.run(make_pipeline_input())
        # Stage 4 ran, produced NO_ALERT, and the pipeline assembled OPPORTUNITY_SCORED_NO_ALERT.
        assert seq.sequence[-1] == StageName.ALERT_DECISION.value
        assert result.result == PipelineResultType.OPPORTUNITY_SCORED_NO_ALERT.value


# ---------------------------------------------------------------------------
# §9 — Outputs passed correctly between stages
# ---------------------------------------------------------------------------

class TestStageOutputsPassedBetweenStages:
    def test_stage2_receives_pipeline_context_and_ref_timestamp(self):
        runner, fakes = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
        )
        runner.run(make_pipeline_input())
        call = fakes["discrepancy"].calls[0]
        assert call["pipeline_execution_id"] == PIPELINE_ID
        assert call["product_id"] == PRODUCT_ID
        # §9.5: freshness_reference_timestamp flows through unchanged.
        assert call["evaluation_reference_timestamp"] == FIXED_TS_STR
        assert call["discrepancy_rule_set"] == {"rule_id": "r1"}

    def test_stage3_receives_stage2_output_verbatim(self):
        disc = make_discrepancy_detected()
        runner, fakes = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=disc,
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
        )
        runner.run(make_pipeline_input())
        call = fakes["scoring"].calls[0]
        # The Stage 2 classification and pair fields are routed forward unchanged.
        assert call["discrepancy_result"] == DiscrepancyResultType.DISCREPANCY_DETECTED.value
        assert call["pair_id"] == PAIR_ID
        assert call["source_a"] == "A"
        assert call["source_b"] == "B"
        assert call["price_a"] == 100.0
        assert call["price_b"] == 120.0
        # §9.5 timestamp consistency at Stage 3.
        assert call["freshness_reference_timestamp"] == FIXED_TS_STR
        assert call["scoring_timestamp"] == FIXED_TS_STR

    def test_stage4_receives_stage3_output_and_resolved_duplicate_check(self):
        runner, fakes = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
        )
        runner.run(make_pipeline_input())
        call = fakes["alert"].calls[0]
        assert call["pipeline_execution_id"] == PIPELINE_ID
        assert call["score_result_id"] == SCORE_RESULT_ID
        assert call["pair_id"] == PAIR_ID
        assert call["score"] == 0.9
        # §9.3 — duplicate check resolved before Stage 4, passed as explicit input.
        assert call["duplicate_check_result"] == DuplicateCheckResult.NO_PRIOR_ALERT.value
        # §9.5 — timestamp consistency at Stage 4.
        assert call["decision_reference_timestamp"] == FIXED_TS_STR

    def test_captured_stage_outputs_are_present_in_final_result(self):
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=make_discrepancy_detected(),
            scoring_result=make_scored_opportunity(),
            alert_result=make_alert_eligible(),
        )
        result = runner.run(make_pipeline_input())
        # §7 Rule 2: every stage output is captured before transition.
        assert "input_validation" in result.stage_outputs
        assert "discrepancy_detection" in result.stage_outputs
        assert "opportunity_scoring" in result.stage_outputs
        assert "alert_decision" in result.stage_outputs
        assert result.stage_outputs["duplicate_check_result"] == (
            DuplicateCheckResult.NO_PRIOR_ALERT.value
        )


# ---------------------------------------------------------------------------
# §6 / §13 — Stage 6 audit/log emission on every outcome
# ---------------------------------------------------------------------------

class TestAuditEmissionEveryOutcome:
    @pytest.mark.parametrize(
        "build_args, expected_final",
        [
            (
                dict(
                    validator_result=make_valid_result(),
                    discrepancy_result=make_discrepancy_detected(),
                    scoring_result=make_scored_opportunity(),
                    alert_result=make_alert_eligible(),
                ),
                PipelineResultType.OPPORTUNITY_DETECTED.value,
            ),
            (
                dict(
                    validator_result=make_valid_result(),
                    discrepancy_result=make_discrepancy_detected(),
                    scoring_result=make_scored_opportunity(),
                    alert_result=make_no_alert(),
                ),
                PipelineResultType.OPPORTUNITY_SCORED_NO_ALERT.value,
            ),
            (
                dict(
                    validator_result=make_valid_result(),
                    discrepancy_result=make_no_discrepancy(),
                ),
                PipelineResultType.NO_OPPORTUNITY.value,
            ),
            (
                dict(
                    validator_result=make_valid_result(),
                    discrepancy_result=make_discrepancy_no_op(),
                ),
                PipelineResultType.NO_OP.value,
            ),
            (
                dict(validator_result=make_invalid_result()),
                PipelineResultType.VALIDATION_FAILURE.value,
            ),
            (
                dict(validator_result=make_precondition_failure()),
                PipelineResultType.PRECONDITION_FAILURE.value,
            ),
            (
                dict(
                    validator_result=make_valid_result(),
                    discrepancy_result=make_discrepancy_processing_failure(),
                ),
                PipelineResultType.PROCESSING_FAILURE.value,
            ),
        ],
        ids=[
            "OPPORTUNITY_DETECTED",
            "OPPORTUNITY_SCORED_NO_ALERT",
            "NO_OPPORTUNITY",
            "NO_OP",
            "VALIDATION_FAILURE",
            "PRECONDITION_FAILURE",
            "PROCESSING_FAILURE",
        ],
    )
    def test_every_outcome_emits_exactly_one_audit_record(
        self, build_args, expected_final
    ):
        sink: list[AuditRecord] = []
        runner, _ = build_runner(audit_sink=sink, **build_args)
        result = runner.run(make_pipeline_input())
        assert result.result == expected_final
        # §6 / §13 — exactly one audit record per execution.
        assert len(sink) == 1
        audit = sink[0]
        assert isinstance(audit, AuditRecord)
        assert audit.pipeline_execution_id
        assert audit.final_result == expected_final
        # Every audit includes the stage outcome summary.
        assert isinstance(audit.stage_outcomes, tuple)
        assert len(audit.stage_outcomes) >= 1
        # Every execution's PipelineResult carries the same audit.
        assert result.audit is audit


# ---------------------------------------------------------------------------
# §7 Rule 8 — Orchestrator PROCESSING_FAILURE uses failure_stage=ORCHESTRATOR
# ---------------------------------------------------------------------------

class TestOrchestratorProcessingFailure:
    def test_unexpected_exception_is_classified_as_orchestrator_failure(self):
        class ExplodingDiscrepancy:
            def evaluate(self, _input):
                raise RuntimeError("unexpected worker explosion")

        sink: list[AuditRecord] = []
        runner = PipelineRunner(
            input_validator_factory=lambda _pi: FakeValidator(make_valid_result()),
            discrepancy_worker=ExplodingDiscrepancy(),
            scoring_worker=FakeScoringWorker(make_scored_opportunity()),
            alert_decision_worker=FakeAlertDecisionWorker(make_alert_eligible()),
            audit_emitter=sink.append,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.ORCHESTRATOR.value
        # §14: not retriable when the orchestrator itself failed.
        assert result.retriable is False
        assert sink and sink[0].failure_stage == StageName.ORCHESTRATOR.value
        assert sink[0].final_result == PipelineResultType.PROCESSING_FAILURE.value

    def test_unexpected_stage1_shape_is_classified_as_orchestrator_failure(self):
        # Validator returns an object that is neither ValidResult, InvalidResult,
        # nor PreconditionFailureResult — the orchestrator must treat this as
        # its own internal error per Rule 8.
        class WeirdValidationResult:
            result = "SOMETHING_ELSE"

        sink: list[AuditRecord] = []
        runner = PipelineRunner(
            input_validator_factory=lambda _pi: FakeValidator(WeirdValidationResult()),
            discrepancy_worker=FakeDiscrepancyWorker(make_discrepancy_detected()),
            scoring_worker=FakeScoringWorker(make_scored_opportunity()),
            alert_decision_worker=FakeAlertDecisionWorker(make_alert_eligible()),
            audit_emitter=sink.append,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.ORCHESTRATOR.value
        assert sink[0].failure_stage == StageName.ORCHESTRATOR.value

    def test_unexpected_stage2_classification_is_orchestrator_failure(self):
        weird = SimpleNamespace(result="MYSTERY_CLASSIFICATION")
        sink: list[AuditRecord] = []
        runner, _ = build_runner(
            validator_result=make_valid_result(),
            discrepancy_result=weird,
            audit_sink=sink,
        )
        result = runner.run(make_pipeline_input())
        assert result.result == PipelineResultType.PROCESSING_FAILURE.value
        assert result.failure_stage == StageName.ORCHESTRATOR.value
