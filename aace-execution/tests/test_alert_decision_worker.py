"""
Unit tests for AlertDecisionWorker — Stage 6.

Contract: Contracts/ALERT_DECISION_CONTRACT.md

All tests use fixed inputs and fixed ISO 8601 timestamps. No system clock,
no randomness, no external calls. Each test asserts exact outputs against
the contract.
"""

from __future__ import annotations

import copy

import pytest # type: ignore

from src.aace_execution.workers.alert_decision_worker import (
    AlertDecisionResultType,
    AlertDecisionWorker,
    AlertEligibleResult,
    DecisionBasisEntry,
    DuplicateCheckResult,
    FailureReason,
    FailureStage,
    NoAlertResult,
    ProcessingFailureResult,
    RuleName,
    RuleResult,
    SuppressionReason,
    _derive_alert_decision_id,
)


# ---------------------------------------------------------------------------
# Fixed test data
# ---------------------------------------------------------------------------

FIXED_PIPELINE_ID   = "pipe-test-alert-001"
FIXED_SCORE_ID      = "score::pipe-test-alert-001::pair-A"
FIXED_PRODUCT_ID    = "product-ABC"
FIXED_PAIR_ID       = "pair-A"
FIXED_NOTIFICATION  = "DISCREPANCY_ALERT_EMAIL"
FIXED_DECISION_TS   = "2025-06-15T12:00:00+00:00"


def make_valid_input(**overrides) -> dict:
    """Build a valid SCORED_OPPORTUNITY decision input. Override via kwargs."""
    base: dict = {
        "pipeline_execution_id": FIXED_PIPELINE_ID,
        "score_result_id":       FIXED_SCORE_ID,
        "product_id":            FIXED_PRODUCT_ID,
        "pair_id":               FIXED_PAIR_ID,
        "scoring_result":        "SCORED_OPPORTUNITY",
        "score":                 0.80,
        "score_range":           {"min": 0.0, "max": 1.0},
        "alert_threshold":       0.70,
        "eligible_opportunity_statuses": ["ACTIVE", "PUBLISHED"],
        "opportunity_status":    "ACTIVE",
        "duplicate_check_result": "NO_PRIOR_ALERT",
        "notification_type":     FIXED_NOTIFICATION,
        "decision_reference_timestamp": FIXED_DECISION_TS,
        "discrepancy_reference": {"discrepancy_result_id": "disc-001"},
        "factors_applied": [
            {"factor_name": "price_gap", "weight": 1.0,
             "weighted_contribution": 0.80},
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def worker() -> AlertDecisionWorker:
    return AlertDecisionWorker()


# ===========================================================================
# TestResultTypes — all three result types are reachable
# ===========================================================================

class TestResultTypes:

    def test_alert_eligible_returned_when_all_rules_pass(self, worker):
        result = worker.evaluate(make_valid_input())
        assert isinstance(result, AlertEligibleResult)
        assert result.result == AlertDecisionResultType.ALERT_ELIGIBLE.value

    def test_no_alert_returned_when_a_rule_fails(self, worker):
        result = worker.evaluate(make_valid_input(score=0.50))
        assert isinstance(result, NoAlertResult)
        assert result.result == AlertDecisionResultType.NO_ALERT.value

    def test_processing_failure_returned_on_invalid_input(self, worker):
        result = worker.evaluate("not-a-dict")
        assert isinstance(result, ProcessingFailureResult)
        assert result.result == AlertDecisionResultType.PROCESSING_FAILURE.value


# ===========================================================================
# TestThresholdRule — Contract §7.1 (inclusive >= semantics)
# ===========================================================================

class TestThresholdRule:

    def test_score_strictly_above_threshold_passes(self, worker):
        result = worker.evaluate(make_valid_input(score=0.95, alert_threshold=0.70))
        assert isinstance(result, AlertEligibleResult)
        assert result.threshold_met is True

    def test_score_exactly_equal_threshold_passes_inclusive(self, worker):
        # §7.1 — boundary is inclusive: score >= alert_threshold.
        result = worker.evaluate(make_valid_input(score=0.70, alert_threshold=0.70))
        assert isinstance(result, AlertEligibleResult)
        assert result.threshold_met is True

    def test_score_just_below_threshold_fails(self, worker):
        result = worker.evaluate(make_valid_input(
            score=0.6999999, alert_threshold=0.70
        ))
        assert isinstance(result, NoAlertResult)
        assert result.threshold_met is False
        assert result.suppression_reason == (
            SuppressionReason.SCORE_BELOW_THRESHOLD.value
        )

    def test_score_far_below_threshold_fails(self, worker):
        result = worker.evaluate(make_valid_input(
            score=0.0, alert_threshold=0.70
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.SCORE_BELOW_THRESHOLD.value
        )

    def test_threshold_at_score_range_max_passes_when_equal(self, worker):
        result = worker.evaluate(make_valid_input(
            score=1.0, alert_threshold=1.0
        ))
        assert isinstance(result, AlertEligibleResult)


# ===========================================================================
# TestStatusRule — Contract §7.2
# ===========================================================================

class TestStatusRule:

    def test_status_in_eligible_list_passes(self, worker):
        result = worker.evaluate(make_valid_input(
            opportunity_status="PUBLISHED",
            eligible_opportunity_statuses=["ACTIVE", "PUBLISHED"],
        ))
        assert isinstance(result, AlertEligibleResult)

    def test_status_not_in_eligible_list_fails(self, worker):
        result = worker.evaluate(make_valid_input(
            opportunity_status="DRAFT",
            eligible_opportunity_statuses=["ACTIVE", "PUBLISHED"],
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.INELIGIBLE_OPPORTUNITY_STATUS.value
        )

    def test_status_is_case_sensitive(self, worker):
        result = worker.evaluate(make_valid_input(
            opportunity_status="active",
            eligible_opportunity_statuses=["ACTIVE"],
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.INELIGIBLE_OPPORTUNITY_STATUS.value
        )

    def test_single_status_list_accepts_matching(self, worker):
        result = worker.evaluate(make_valid_input(
            opportunity_status="ACTIVE",
            eligible_opportunity_statuses=["ACTIVE"],
        ))
        assert isinstance(result, AlertEligibleResult)


# ===========================================================================
# TestDuplicateRule — Contract §7.3
# ===========================================================================

class TestDuplicateRule:

    def test_no_prior_alert_passes(self, worker):
        result = worker.evaluate(make_valid_input(
            duplicate_check_result="NO_PRIOR_ALERT"
        ))
        assert isinstance(result, AlertEligibleResult)
        assert result.duplicate_check_result == (
            DuplicateCheckResult.NO_PRIOR_ALERT.value
        )

    def test_prior_alert_exists_fails(self, worker):
        result = worker.evaluate(make_valid_input(
            duplicate_check_result="PRIOR_ALERT_EXISTS"
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.DUPLICATE_ALERT_SUPPRESSED.value
        )

    def test_unrecognized_duplicate_value_is_precondition_failure(self, worker):
        # §5.6 — unknown value is a PROCESSING_FAILURE, not NO_ALERT.
        result = worker.evaluate(make_valid_input(
            duplicate_check_result="MAYBE"
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )


# ===========================================================================
# TestRuleOrderAndShortCircuit — Contract §7.5
# ===========================================================================

class TestRuleOrderAndShortCircuit:

    def test_threshold_fail_short_circuits_before_status_and_duplicate(
        self, worker
    ):
        # Threshold fails; status is also bad; duplicate is also bad.
        # Only SCORE_THRESHOLD must appear in decision_basis.
        result = worker.evaluate(make_valid_input(
            score=0.10,
            opportunity_status="DRAFT",
            eligible_opportunity_statuses=["ACTIVE"],
            duplicate_check_result="PRIOR_ALERT_EXISTS",
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.SCORE_BELOW_THRESHOLD.value
        )
        assert len(result.decision_basis) == 1
        assert result.decision_basis[0].rule_name == (
            RuleName.SCORE_THRESHOLD.value
        )
        assert result.decision_basis[0].rule_result == RuleResult.FAILED.value

    def test_status_fail_short_circuits_before_duplicate(self, worker):
        # Threshold passes, status fails, duplicate also bad.
        # decision_basis must contain exactly [THRESHOLD PASSED, STATUS FAILED].
        result = worker.evaluate(make_valid_input(
            score=0.90,
            opportunity_status="DRAFT",
            eligible_opportunity_statuses=["ACTIVE"],
            duplicate_check_result="PRIOR_ALERT_EXISTS",
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.INELIGIBLE_OPPORTUNITY_STATUS.value
        )
        rule_names = [e.rule_name for e in result.decision_basis]
        assert rule_names == [
            RuleName.SCORE_THRESHOLD.value,
            RuleName.ELIGIBLE_STATUS.value,
        ]
        assert result.decision_basis[0].rule_result == RuleResult.PASSED.value
        assert result.decision_basis[1].rule_result == RuleResult.FAILED.value

    def test_duplicate_fail_after_threshold_and_status_pass(self, worker):
        # All three rules must be evaluated; duplicate fails.
        result = worker.evaluate(make_valid_input(
            score=0.90,
            opportunity_status="ACTIVE",
            duplicate_check_result="PRIOR_ALERT_EXISTS",
        ))
        assert isinstance(result, NoAlertResult)
        assert result.suppression_reason == (
            SuppressionReason.DUPLICATE_ALERT_SUPPRESSED.value
        )
        rule_names = [e.rule_name for e in result.decision_basis]
        assert rule_names == [
            RuleName.SCORE_THRESHOLD.value,
            RuleName.ELIGIBLE_STATUS.value,
            RuleName.DUPLICATE_PREVENTION.value,
        ]
        assert [e.rule_result for e in result.decision_basis] == [
            RuleResult.PASSED.value,
            RuleResult.PASSED.value,
            RuleResult.FAILED.value,
        ]

    def test_all_pass_records_all_three_rules_in_order(self, worker):
        result = worker.evaluate(make_valid_input())
        assert isinstance(result, AlertEligibleResult)
        assert [e.rule_name for e in result.decision_basis] == [
            RuleName.SCORE_THRESHOLD.value,
            RuleName.ELIGIBLE_STATUS.value,
            RuleName.DUPLICATE_PREVENTION.value,
        ]
        for entry in result.decision_basis:
            assert entry.rule_result == RuleResult.PASSED.value
            assert entry.reason is None

    def test_decision_basis_entries_are_dataclass_instances(self, worker):
        result = worker.evaluate(make_valid_input())
        for entry in result.decision_basis:
            assert isinstance(entry, DecisionBasisEntry)


# ===========================================================================
# TestPreconditionFailures — Contract §5 / §9
# ===========================================================================

class TestPreconditionFailures:

    def test_missing_pipeline_execution_id(self, worker):
        inp = make_valid_input()
        inp.pop("pipeline_execution_id")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )
        assert result.failure_stage == FailureStage.PRECONDITION_CHECK.value

    def test_missing_score_result_id(self, worker):
        inp = make_valid_input()
        inp.pop("score_result_id")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_empty_product_id(self, worker):
        result = worker.evaluate(make_valid_input(product_id=""))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_scoring_result_not_scored_opportunity(self, worker):
        result = worker.evaluate(make_valid_input(scoring_result="NO_SCORE"))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_score_not_numeric(self, worker):
        result = worker.evaluate(make_valid_input(score="high"))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_score_is_bool_is_rejected(self, worker):
        # bool is a subclass of int — must be rejected explicitly.
        result = worker.evaluate(make_valid_input(score=True))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_score_infinite_is_rejected(self, worker):
        result = worker.evaluate(make_valid_input(score=float("inf")))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_score_nan_is_rejected(self, worker):
        result = worker.evaluate(make_valid_input(score=float("nan")))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_score_outside_range_is_rejected(self, worker):
        result = worker.evaluate(make_valid_input(
            score=1.5, score_range={"min": 0.0, "max": 1.0}
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_score_range_min_ge_max_is_rejected(self, worker):
        result = worker.evaluate(make_valid_input(
            score=0.5, score_range={"min": 1.0, "max": 1.0}
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_alert_threshold_missing(self, worker):
        inp = make_valid_input()
        inp.pop("alert_threshold")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )

    def test_alert_threshold_non_numeric(self, worker):
        result = worker.evaluate(make_valid_input(alert_threshold="high"))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_THRESHOLD_CONFIGURATION.value
        )

    def test_alert_threshold_bool_is_rejected(self, worker):
        result = worker.evaluate(make_valid_input(alert_threshold=True))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_THRESHOLD_CONFIGURATION.value
        )

    def test_alert_threshold_outside_score_range_rejected(self, worker):
        result = worker.evaluate(make_valid_input(
            alert_threshold=1.5, score_range={"min": 0.0, "max": 1.0}
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_THRESHOLD_CONFIGURATION.value
        )

    def test_eligible_statuses_missing(self, worker):
        inp = make_valid_input()
        inp.pop("eligible_opportunity_statuses")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )

    def test_eligible_statuses_empty_list(self, worker):
        result = worker.evaluate(make_valid_input(
            eligible_opportunity_statuses=[]
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )

    def test_eligible_statuses_contains_non_string(self, worker):
        result = worker.evaluate(make_valid_input(
            eligible_opportunity_statuses=["ACTIVE", 42]
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )

    def test_opportunity_status_missing(self, worker):
        inp = make_valid_input()
        inp.pop("opportunity_status")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_duplicate_check_missing(self, worker):
        inp = make_valid_input()
        inp.pop("duplicate_check_result")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_notification_type_missing(self, worker):
        inp = make_valid_input()
        inp.pop("notification_type")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )

    def test_decision_reference_timestamp_missing(self, worker):
        inp = make_valid_input()
        inp.pop("decision_reference_timestamp")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.PRECONDITION_VIOLATION.value
        )

    def test_decision_reference_timestamp_malformed(self, worker):
        result = worker.evaluate(make_valid_input(
            decision_reference_timestamp="not-a-timestamp"
        ))
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )

    def test_non_dict_input_rejected(self, worker):
        result = worker.evaluate(["not", "a", "dict"])
        assert isinstance(result, ProcessingFailureResult)
        assert result.failure_reason == (
            FailureReason.INVALID_SCORED_OPPORTUNITY_INPUT.value
        )
        assert result.failure_stage == FailureStage.INPUT_PARSE.value


# ===========================================================================
# TestDeterminism — Contract §10
# ===========================================================================

class TestDeterminism:

    def test_same_input_same_output_alert_eligible(self, worker):
        inp = make_valid_input()
        r1 = worker.evaluate(copy.deepcopy(inp))
        r2 = worker.evaluate(copy.deepcopy(inp))
        assert r1 == r2

    def test_same_input_same_output_no_alert(self, worker):
        inp = make_valid_input(score=0.10)
        r1 = worker.evaluate(copy.deepcopy(inp))
        r2 = worker.evaluate(copy.deepcopy(inp))
        assert r1 == r2

    def test_same_input_same_output_failure(self, worker):
        inp = make_valid_input(alert_threshold="bogus")
        r1 = worker.evaluate(copy.deepcopy(inp))
        r2 = worker.evaluate(copy.deepcopy(inp))
        assert r1 == r2

    def test_alert_decision_id_is_stable_and_deterministic(self, worker):
        # §8.1, §10.11, §11.2 — id derived from pipeline_execution_id + notification_type.
        result = worker.evaluate(make_valid_input())
        assert isinstance(result, AlertEligibleResult)
        expected = f"alert::{FIXED_PIPELINE_ID}::{FIXED_NOTIFICATION}"
        assert result.alert_decision_id == expected

    def test_alert_decision_id_derivation_matches_helper(self):
        expected = _derive_alert_decision_id(
            pipeline_execution_id=FIXED_PIPELINE_ID,
            notification_type=FIXED_NOTIFICATION,
        )
        assert expected == f"alert::{FIXED_PIPELINE_ID}::{FIXED_NOTIFICATION}"

    def test_alert_decision_id_changes_when_pipeline_changes(self, worker):
        r1 = worker.evaluate(make_valid_input(
            pipeline_execution_id="pipe-AAA"
        ))
        r2 = worker.evaluate(make_valid_input(
            pipeline_execution_id="pipe-BBB"
        ))
        assert r1.alert_decision_id != r2.alert_decision_id

    def test_alert_decision_id_changes_when_notification_type_changes(
        self, worker
    ):
        r1 = worker.evaluate(make_valid_input(
            notification_type="EMAIL"
        ))
        r2 = worker.evaluate(make_valid_input(
            notification_type="SLACK"
        ))
        assert r1.alert_decision_id != r2.alert_decision_id

    def test_evaluate_does_not_mutate_input(self, worker):
        inp = make_valid_input()
        snapshot = copy.deepcopy(inp)
        worker.evaluate(inp)
        assert inp == snapshot

    def test_repeated_no_alert_has_identical_decision_basis(self, worker):
        inp = make_valid_input(score=0.10)
        r1 = worker.evaluate(copy.deepcopy(inp))
        r2 = worker.evaluate(copy.deepcopy(inp))
        assert r1.decision_basis == r2.decision_basis


# ===========================================================================
# TestOutputStructure — Contract §8.1, §8.2, §8.3
# ===========================================================================

class TestOutputStructure:

    def test_alert_eligible_contains_required_fields(self, worker):
        result = worker.evaluate(make_valid_input())
        assert isinstance(result, AlertEligibleResult)
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.alert_decision_id.startswith("alert::")
        assert result.score_result_id == FIXED_SCORE_ID
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pair_id == FIXED_PAIR_ID
        assert result.score == 0.80
        assert result.alert_threshold == 0.70
        assert result.threshold_met is True
        assert result.opportunity_status == "ACTIVE"
        assert result.eligible_statuses_used == ("ACTIVE", "PUBLISHED")
        assert result.duplicate_check_result == (
            DuplicateCheckResult.NO_PRIOR_ALERT.value
        )
        assert result.notification_type == FIXED_NOTIFICATION
        assert result.decision_reference_timestamp == FIXED_DECISION_TS
        assert isinstance(result.discrepancy_reference, dict)
        assert isinstance(result.scoring_factor_summary, tuple)

    def test_alert_eligible_threshold_met_always_true(self, worker):
        result = worker.evaluate(make_valid_input())
        assert result.threshold_met is True

    def test_alert_eligible_duplicate_is_always_no_prior(self, worker):
        result = worker.evaluate(make_valid_input())
        assert result.duplicate_check_result == (
            DuplicateCheckResult.NO_PRIOR_ALERT.value
        )

    def test_no_alert_contains_required_fields(self, worker):
        result = worker.evaluate(make_valid_input(score=0.10))
        assert isinstance(result, NoAlertResult)
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.alert_decision_id == (
            f"alert::{FIXED_PIPELINE_ID}::{FIXED_NOTIFICATION}"
        )
        assert result.score_result_id == FIXED_SCORE_ID
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pair_id == FIXED_PAIR_ID
        assert result.score == 0.10
        assert result.alert_threshold == 0.70
        assert result.suppression_reason in {r.value for r in SuppressionReason}
        assert result.decision_reference_timestamp == FIXED_DECISION_TS
        assert result.notification_type == FIXED_NOTIFICATION

    def test_no_alert_threshold_met_reflects_rule(self, worker):
        # When threshold is the failing rule, threshold_met must be False.
        r = worker.evaluate(make_valid_input(score=0.10))
        assert r.threshold_met is False
        # When later rule fails, threshold_met should be True.
        r2 = worker.evaluate(make_valid_input(
            opportunity_status="DRAFT",
            eligible_opportunity_statuses=["ACTIVE"],
        ))
        assert r2.threshold_met is True

    def test_processing_failure_contains_required_fields(self, worker):
        inp = make_valid_input()
        inp.pop("alert_threshold")
        result = worker.evaluate(inp)
        assert isinstance(result, ProcessingFailureResult)
        assert result.result == AlertDecisionResultType.PROCESSING_FAILURE.value
        assert result.pipeline_execution_id == FIXED_PIPELINE_ID
        assert result.score_result_id == FIXED_SCORE_ID
        assert result.product_id == FIXED_PRODUCT_ID
        assert result.pair_id == FIXED_PAIR_ID
        assert result.failure_reason == (
            FailureReason.MISSING_ALERT_CONFIGURATION.value
        )
        assert result.failure_stage == FailureStage.PRECONDITION_CHECK.value
        assert isinstance(result.retriable, bool)
        assert isinstance(result.error_context, str)
        assert result.error_context != ""

    def test_processing_failure_on_non_dict_has_none_identifiers(self, worker):
        result = worker.evaluate(None)
        assert isinstance(result, ProcessingFailureResult)
        assert result.pipeline_execution_id is None
        assert result.score_result_id is None
        assert result.product_id is None
        assert result.pair_id is None

    def test_decision_basis_reason_none_for_passed(self, worker):
        result = worker.evaluate(make_valid_input())
        for entry in result.decision_basis:
            assert entry.rule_result == RuleResult.PASSED.value
            assert entry.reason is None

    def test_decision_basis_reason_set_for_failed(self, worker):
        result = worker.evaluate(make_valid_input(score=0.10))
        failed = [e for e in result.decision_basis
                  if e.rule_result == RuleResult.FAILED.value]
        assert len(failed) == 1
        assert failed[0].reason == (
            SuppressionReason.SCORE_BELOW_THRESHOLD.value
        )
