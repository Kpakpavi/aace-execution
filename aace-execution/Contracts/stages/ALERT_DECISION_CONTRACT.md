# Alert Decision Contract

## 1. Purpose

This document is the authoritative contract for the Alert Decision Worker — Stage 6 of the
AACE Opportunity Pipeline.

It defines:

- what this worker does and why it exists,
- what inputs it requires and what preconditions must be satisfied before it runs,
- the exact scope of alert evaluation it must perform,
- the rules it must apply to reach a deterministic alert eligibility decision,
- what outputs it must produce,
- how it must behave under failure,
- what it must never do.

This is not an implementation document.
It does not contain code, pseudocode, or framework-specific instructions.
It defines the behavioral contract that implementation must satisfy.

---

## 2. Relationship to Spec Repo

This worker implements behavior defined in the following AACE spec directives:

- `directives/spec/features/alerts/00_overview.md` — feature objective, determinism requirement, explainability requirement, noise control
- `directives/spec/features/alerts/01_requirements.md` — trigger conditions, threshold requirements, duplicate prevention, alert generation, failure handling
- `directives/spec/features/alerts/02_acceptance_criteria.md` — trigger condition acceptance, threshold enforcement, duplicate prevention, alert message, explainability, failure handling, non-acceptance conditions
- `directives/spec/features/alerts/03_notification_rules.md` — trigger model, required conditions, score threshold rule, eligible opportunity status rule, duplicate prevention rules, notification identity rule, noise reduction rules, determinism rules, explainability rules, failure rules
- `directives/spec/features/opportunity_scoring/01_requirements.md` — scored opportunity structure consumed by this worker
- `directives/spec/06_architecture.md` — three-layer model, pipeline data flow, domain responsibilities
- `directives/spec/12_autonomous_execution_constraints.md` — execution boundary rules

This worker must never redefine the alert thresholds, eligibility conditions, duplicate
prevention rules, or noise reduction rules those directives establish.
If an alert rule is missing, ambiguous, or in conflict, implementation must stop and the spec
must be updated first.

Business rules flow one direction: spec → this worker.

---

## 3. Worker Objective

The Alert Decision Worker is the stage that determines whether a scored opportunity qualifies
to trigger an alert under the spec-defined alert conditions.

Its objective is to consume a valid `SCORED_OPPORTUNITY` result and produce a single deterministic
decision indicating whether that opportunity is eligible for an alert notification.

The worker must:

- confirm that the incoming scored opportunity satisfies alert evaluation preconditions,
- evaluate the opportunity score against the spec-defined alert threshold,
- evaluate the opportunity status against spec-defined eligible status conditions,
- check that the duplicate prevention rule does not block generation for this opportunity
  and trigger condition (using information provided as input — no external lookups),
- produce a structured decision result classifying the outcome as `ALERT_ELIGIBLE`,
  `NO_ALERT`, or `PROCESSING_FAILURE`,
- preserve the explanation-ready basis for the decision so it is traceable without
  additional context.

The worker must not:

- send, queue, or deliver notifications of any kind,
- persist alert records to any system of record,
- score opportunities,
- fetch or enrich data from external sources,
- redefine the alert threshold, eligible status values, or duplicate prevention policy.

---

## 4. Required Inputs

The worker requires a single structured input containing the following:

**Scored Opportunity Result (from Stage 5)**

- `pipeline_execution_id` — the unique identifier for this pipeline run, carried forward from Stage 1.
- `score_result_id` — the deterministic score result identifier produced by Stage 5.
- `product_id` — stable product identifier, carried from upstream without modification.
- `pair_id` — the canonical pair identifier carried from Stage 4.
- `score` — the numeric score produced by Stage 5. Must be a finite number within the configured score range.
- `score_range` — the configured minimum and maximum of the score range applied during scoring.
- `scoring_result` — must be `SCORED_OPPORTUNITY`; any other value is a precondition failure.
- `discrepancy_reference` — the discrepancy context echo from Stage 5, including: `source_a`, `source_b`, `price_a`, `price_b`, `absolute_difference`, `percentage_difference`, `threshold_method`.
- `factors_applied` — the list of scoring factor contributions from Stage 5. Preserved for explanation.

**Alert Configuration (from spec-defined rule set)**

- `alert_threshold` — the minimum score value at or above which an opportunity is eligible for an alert. Must be explicitly defined; must not be absent or null.
- `eligible_opportunity_statuses` — the list of opportunity statuses that qualify for alert evaluation (e.g., `["active"]`). Must be non-empty.
- `opportunity_status` — the current status of the opportunity being evaluated. Must be present and checked against `eligible_opportunity_statuses`.
- `duplicate_check_result` — an explicit, pre-resolved indicator provided by the pipeline coordinator stating whether a prior alert already exists for this opportunity and trigger condition. One of: `NO_PRIOR_ALERT`, `PRIOR_ALERT_EXISTS`. This worker does not perform the duplicate lookup itself.
- `notification_type` — the type of notification condition being evaluated (e.g., `NEW_OPPORTUNITY_ABOVE_THRESHOLD`). Used for explanation context and duplicate scoping.

**Reference Timestamp**

- `decision_reference_timestamp` — an explicit ISO 8601 timestamp passed into this worker
  representing the point in time at which this decision is being made.
  This timestamp must never be derived from the system clock within the worker.

No input field may be inferred, defaulted silently, or invented by this worker.
If a required field is absent, the worker must reject the input with a structured
`PROCESSING_FAILURE` identifying the missing field.

---

## 5. Preconditions

The following preconditions must be satisfied before this worker begins evaluation.
If any precondition is not met, the worker must halt immediately with a structured failure result.
It must not attempt to evaluate alert eligibility.

1. The incoming `scoring_result` is `SCORED_OPPORTUNITY`. Any other value is a precondition violation.
2. The `score` field is a finite number within the configured `score_range`. A null, non-finite, or out-of-range score is a precondition violation.
3. The `alert_threshold` is present, non-null, and a valid number within the configured `score_range`.
4. The `eligible_opportunity_statuses` list is non-empty.
5. The `opportunity_status` field is present and non-null.
6. The `duplicate_check_result` field is present and contains one of the recognized values: `NO_PRIOR_ALERT` or `PRIOR_ALERT_EXISTS`.
7. The `notification_type` field is present and non-empty.
8. The `decision_reference_timestamp` is present and a valid ISO 8601 timestamp.
9. The `pipeline_execution_id` is present and non-empty.
10. The `score_result_id` is present and non-empty.

A precondition failure is not an eligibility decision.
It is a structural rejection indicating this worker should not have been invoked in this state.
It must be returned as a structured `PROCESSING_FAILURE` with failure reason
`PRECONDITION_VIOLATION`.

---

## 6. Alert Evaluation Scope

This worker evaluates exactly one scored opportunity per invocation.
It does not batch, aggregate, or compare across multiple opportunities.

The worker evaluates:

- whether the opportunity's `score` meets or exceeds the `alert_threshold` (`score >= alert_threshold`),
- whether the opportunity's `opportunity_status` is present in `eligible_opportunity_statuses`,
- whether the pre-resolved `duplicate_check_result` permits alert generation for this opportunity and trigger condition.

The threshold boundary semantic is inclusive: a score exactly equal to `alert_threshold` meets
the threshold. This is consistent with the boundary semantic established in the discrepancy
detection stage.

The worker does not evaluate:

- whether the discrepancy was correctly detected (Stage 4),
- whether the score was correctly computed (Stage 5),
- whether to send or schedule a notification (downstream concern, outside this pipeline),
- whether a prior alert record exists — the pipeline coordinator provides that resolution
  as `duplicate_check_result`; this worker applies the result, it does not perform the lookup.

---

## 7. Alert Decision Rules

This section defines the decision rules this worker must apply.
These rules are derived from `directives/spec/features/alerts/03_notification_rules.md`.

### 7.1 Score Threshold Rule

A scored opportunity is eligible for an alert only if:

```
score >= alert_threshold
```

Where:

- `score` is the value produced by Stage 5.
- `alert_threshold` is loaded from the spec-defined alert configuration.
- The `>=` boundary is inclusive: a score exactly equal to the threshold meets the condition.

A score strictly below `alert_threshold` produces a `NO_ALERT` result with reason
`SCORE_BELOW_THRESHOLD`.

### 7.2 Eligible Status Rule

A scored opportunity is eligible for an alert only if:

```
opportunity_status ∈ eligible_opportunity_statuses
```

Where `eligible_opportunity_statuses` is loaded from configuration.
For MVP, the default eligible status is `active`.

An opportunity with a status not in the eligible list produces a `NO_ALERT` result with reason
`INELIGIBLE_OPPORTUNITY_STATUS`.

### 7.3 Duplicate Prevention Rule

A scored opportunity is not eligible for an alert if:

```
duplicate_check_result == PRIOR_ALERT_EXISTS
```

Where `duplicate_check_result` is the pre-resolved indicator provided by the pipeline coordinator.

If a prior alert already exists for the same opportunity and `notification_type`, this worker
must return a `NO_ALERT` result with reason `DUPLICATE_ALERT_SUPPRESSED`.

This worker applies the duplicate check result — it does not perform the lookup.
Performing the lookup is the pipeline coordinator's responsibility.

### 7.4 Combined Eligibility

An opportunity is `ALERT_ELIGIBLE` only if all three rules are satisfied simultaneously:

1. `score >= alert_threshold`, AND
2. `opportunity_status ∈ eligible_opportunity_statuses`, AND
3. `duplicate_check_result == NO_PRIOR_ALERT`.

If any one condition is not satisfied, the result is `NO_ALERT`.

### 7.5 Rule Evaluation Order

Rules must be evaluated in this order:

1. Score threshold (Section 7.1).
2. Eligible status (Section 7.2).
3. Duplicate prevention (Section 7.3).

If the score threshold is not met, evaluation stops and `NO_ALERT` is returned with reason
`SCORE_BELOW_THRESHOLD`. Rules 7.2 and 7.3 are not evaluated.

If the score threshold is met but status is ineligible, evaluation stops and `NO_ALERT` is
returned with reason `INELIGIBLE_OPPORTUNITY_STATUS`. Rule 7.3 is not evaluated.

If both threshold and status conditions are met but a prior alert exists, `NO_ALERT` is
returned with reason `DUPLICATE_ALERT_SUPPRESSED`.

The evaluation order must be deterministic and must be reflected in the output's
`decision_basis` list.

---

## 8. Alert Decision Output Structure

### 8.1 ALERT_ELIGIBLE

Produced when all preconditions are satisfied and all three alert decision rules are met.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `ALERT_ELIGIBLE`. |
| `pipeline_execution_id` | string | Carried from input without modification. |
| `alert_decision_id` | string | A deterministic identifier derived from `pipeline_execution_id` and `notification_type`. Must be stable across retries. |
| `score_result_id` | string | Carried from input without modification. |
| `product_id` | string | Carried from input without modification. |
| `pair_id` | string | Carried from input without modification. |
| `score` | number | The score evaluated against the threshold, carried from input. |
| `alert_threshold` | number | The configured threshold applied. |
| `threshold_met` | boolean | Always `true` for `ALERT_ELIGIBLE`. |
| `opportunity_status` | string | The status evaluated, carried from input. |
| `eligible_statuses_used` | list | The full list of eligible statuses loaded from configuration. |
| `duplicate_check_result` | string | Always `NO_PRIOR_ALERT` for `ALERT_ELIGIBLE`. |
| `notification_type` | string | The notification condition evaluated, carried from input. |
| `decision_basis` | list | Ordered list of rule evaluations applied, each including: `rule_name`, `rule_result` (`PASSED` or `FAILED`), `reason` (populated for FAILED; null for PASSED). |
| `discrepancy_reference` | object | Echo of the key discrepancy fields from Stage 5 input. Preserved for downstream explanation. |
| `scoring_factor_summary` | list | Echo of `factors_applied` from Stage 5. Preserved for explanation traceability. |
| `decision_reference_timestamp` | string | The ISO 8601 reference timestamp passed into this worker, included for auditability. |

### 8.2 NO_ALERT

Produced when all preconditions are satisfied but at least one alert decision rule is not met.
`NO_ALERT` is a valid, expected outcome — not a failure.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `NO_ALERT`. |
| `pipeline_execution_id` | string | Carried from input without modification. |
| `alert_decision_id` | string | A deterministic identifier derived from `pipeline_execution_id` and `notification_type`. Same derivation method as `ALERT_ELIGIBLE`. |
| `score_result_id` | string | Carried from input without modification. |
| `product_id` | string | Carried from input without modification. |
| `pair_id` | string | Carried from input without modification. |
| `score` | number | The score evaluated against the threshold. |
| `alert_threshold` | number | The configured threshold applied. |
| `threshold_met` | boolean | `true` if score met threshold, `false` otherwise. |
| `suppression_reason` | string | The primary reason no alert was generated. One of: `SCORE_BELOW_THRESHOLD`, `INELIGIBLE_OPPORTUNITY_STATUS`, `DUPLICATE_ALERT_SUPPRESSED`. |
| `decision_basis` | list | Ordered list of rule evaluations applied, each including: `rule_name`, `rule_result`, `reason`. Evaluation stops at the first failed rule. |
| `notification_type` | string | The notification condition evaluated. |
| `decision_reference_timestamp` | string | The ISO 8601 reference timestamp passed into this worker. |

### 8.3 PROCESSING_FAILURE

Produced when a runtime error, configuration error, or precondition violation prevents the
alert decision from completing.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `PROCESSING_FAILURE`. |
| `pipeline_execution_id` | string | Carried from input if present; null if failure occurred before input could be parsed. |
| `score_result_id` | string | Carried from input if present; null otherwise. |
| `product_id` | string | Carried from input if present; null otherwise. |
| `pair_id` | string | Carried from input if present; null otherwise. |
| `failure_reason` | string | One of: `PRECONDITION_VIOLATION`, `INVALID_SCORED_OPPORTUNITY_INPUT`, `MISSING_ALERT_CONFIGURATION`, `INVALID_THRESHOLD_CONFIGURATION`, `UNEXPECTED_RUNTIME_ERROR`. |
| `failure_stage` | string | The sub-stage within this worker where the failure occurred (e.g., `PRECONDITION_CHECK`, `THRESHOLD_EVALUATION`, `STATUS_EVALUATION`, `DUPLICATE_CHECK_APPLICATION`). |
| `retriable` | boolean | `true` if the failure is transient and a retry may succeed; `false` if the input or configuration must be corrected first. |
| `error_context` | string | A human-readable description of the failure cause, safe to log without exposing secrets or raw credential payloads. |

---

## 9. Failure Modes

### 9.1 Invalid Scored Opportunity Input

- **Cause**: The incoming scored opportunity is missing required fields, contains malformed values, or presents a `scoring_result` other than `SCORED_OPPORTUNITY`.
- **Failure reason**: `INVALID_SCORED_OPPORTUNITY_INPUT`.
- **Retriable**: No — the upstream scored opportunity result must be corrected or re-evaluated before this stage can proceed.
- **Behavior**: Immediate halt, no evaluation attempted, structured `PROCESSING_FAILURE` returned.

### 9.2 Missing Alert Configuration

- **Cause**: The `alert_threshold` is absent or null, `eligible_opportunity_statuses` is empty or absent, or `notification_type` is absent or empty.
- **Failure reason**: `MISSING_ALERT_CONFIGURATION`.
- **Retriable**: No — configuration must be corrected before rerunning.
- **Behavior**: Immediate halt, structured `PROCESSING_FAILURE` returned.

### 9.3 Invalid Threshold Configuration

- **Cause**: The `alert_threshold` is present but not a valid number, is non-finite, or falls outside the boundaries of the configured `score_range`.
- **Failure reason**: `INVALID_THRESHOLD_CONFIGURATION`.
- **Retriable**: No — the threshold configuration must be corrected before rerunning.
- **Behavior**: Immediate halt, structured `PROCESSING_FAILURE` returned.

### 9.4 Unexpected Runtime Error

- **Cause**: An unhandled exception or unexpected internal state that does not fall into the above categories.
- **Failure reason**: `UNEXPECTED_RUNTIME_ERROR`.
- **Retriable**: Yes — treat as potentially transient; retry up to the configured limit.
- **Behavior**: Explicit exception surfaced, structured `PROCESSING_FAILURE` returned with full error context.

---

## 10. Determinism Rules

The following rules govern the deterministic behavior of this worker.
Violating any rule is a non-acceptance condition.

1. **Same input → same decision.** Given identical scored opportunity input and identical alert configuration, this worker must produce the same decision on every execution, without exception.
2. **No hidden engagement heuristics.** The alert eligibility decision must be based solely on the three rules defined in Section 7. No user-targeting logic, engagement signals, click-through history, or behavioral heuristics may influence the outcome.
3. **No runtime AI decisions.** No AI model may be called within this worker to determine eligibility, adjust thresholds, evaluate opportunity significance, or produce any aspect of the output. All logic is deterministic and code-defined.
4. **No system-clock-derived timing.** The `decision_reference_timestamp` must be passed explicitly into this worker. The system clock must never be read inside this worker for any decision purpose.
5. **No random delivery behavior.** The decision outcome must not vary based on random number generation, probabilistic routing, or any non-deterministic branching.
6. **Inclusive threshold semantics.** The threshold comparison is always `score >= alert_threshold`. This must not silently vary to `>` or any other boundary.
7. **Evaluation order is fixed.** Rules must always be evaluated in the order defined in Section 7.5 (threshold → status → duplicate). The order must not vary based on input values or runtime conditions.
8. **No alert configuration invention.** The `alert_threshold`, `eligible_opportunity_statuses`, and `notification_type` must be loaded from configuration. They must not be hardcoded or adjusted within this worker.
9. **No duplicate check performed internally.** This worker applies the pre-resolved `duplicate_check_result` provided as input. It must not perform its own database lookup or state query to resolve this value.
10. **Decision timestamp must be passed in.** The `decision_reference_timestamp` in the output must be the value provided as explicit input to this worker, not derived from the system clock.
11. **`alert_decision_id` is deterministic.** It must be derived from `pipeline_execution_id` and `notification_type`. It must not be generated randomly.

---

## 11. Idempotency Considerations

This worker does not persist data.
It is a pure decision stage.

However, the following idempotency rules apply to preserve pipeline-level idempotency:

1. Running this worker multiple times on the same input must produce the same decision result, including the same `alert_decision_id`.
2. The `alert_decision_id` must be derived deterministically from `pipeline_execution_id` and `notification_type`. It must not be generated randomly.
3. This worker does not check for existing alert records itself. The `duplicate_check_result` input value encapsulates that resolution, provided by the pipeline coordinator.
4. If this worker is retried after a `PROCESSING_FAILURE`, it must re-execute from the beginning of its evaluation using the same inputs. It must not resume from a partial intermediate state.
5. The same `SCORED_OPPORTUNITY` input presented twice must produce the same `ALERT_ELIGIBLE` or `NO_ALERT` result with the same `alert_decision_id`.

---

## 12. Logging Requirements

This worker must emit a structured log entry at each of the following points:

- **Worker start**: `pipeline_execution_id`, `score_result_id`, `product_id`, `score`, `alert_threshold`, `notification_type`.
- **Precondition check completion**: pass or fail; if fail, which precondition was violated.
- **Threshold evaluation**: `score`, `alert_threshold`, result (`PASSED` or `FAILED`).
- **Status evaluation** (if reached): `opportunity_status`, `eligible_opportunity_statuses`, result (`PASSED` or `FAILED`).
- **Duplicate check application** (if reached): `duplicate_check_result`, result (`PASSED` or `FAILED`).
- **Worker end**: `result`, `suppression_reason` (if `NO_ALERT`), total evaluation time.
- **Any failure**: `failure_reason`, `failure_stage`, `retriable` status, `error_context`.

Logs must be structured and machine-readable.
Logs must never include secrets, credentials, tokens, or raw API response payloads.
Logs must not include the full `discrepancy_reference` or `factors_applied` payload at INFO
level — these should be logged only at DEBUG level to avoid excessive log volume.

---

## 13. What This Worker Must NOT Do

The following are explicitly forbidden in this worker:

- **Send, queue, or schedule notifications.** This worker produces a decision only. Delivering or enqueuing a notification is a downstream concern outside this pipeline stage.
- **Persist alert records.** This worker produces a structured in-memory result. Writing alert records to any system of record is outside this worker's scope.
- **Score opportunities.** Scoring is Stage 5's responsibility. This worker consumes a completed `SCORED_OPPORTUNITY` result; it does not re-evaluate the score.
- **Fetch or enrich data from external sources.** All data needed for the decision must be present in the inputs passed to this worker. No external API calls, database reads, or network requests may be made.
- **Perform duplicate lookup internally.** The pipeline coordinator resolves whether a prior alert exists and provides that result as `duplicate_check_result`. This worker applies that result — it does not query for it.
- **Redefine alert thresholds, eligible statuses, or notification policy.** These are owned by the spec. They must be loaded from configuration — never hardcoded or adjusted within this worker.
- **Call an AI model at runtime.** No large language model, ML model, or probabilistic system may be invoked to determine eligibility, adjust thresholds, or produce any decision output.
- **Use the system clock for decision timing.** All time references must use the `decision_reference_timestamp` provided as explicit input.
- **Apply engagement heuristics.** The decision must be based solely on the score threshold, opportunity status, and duplicate check. No behavioral, targeting, or engagement signals may influence the outcome.
- **Produce a partial or ambiguous decision.** If this worker cannot produce a complete `ALERT_ELIGIBLE` or `NO_ALERT` result, it must produce a `PROCESSING_FAILURE`. An incomplete decision must never be returned as valid output.
- **Swallow exceptions silently.** Every failure must surface as a structured `PROCESSING_FAILURE` result with a classified `failure_reason`.
- **Treat `NO_ALERT` as a failure.** A scored opportunity that does not meet alert conditions is a valid, expected outcome. `NO_ALERT` must never be logged or reported as an error.
- **Operate on more than one scored opportunity per invocation.** This worker evaluates exactly one scored opportunity per call.

---

## 14. Success Criteria

This worker is successful when:

1. A valid `SCORED_OPPORTUNITY` with score at or above `alert_threshold`, an eligible status, and `duplicate_check_result == NO_PRIOR_ALERT` produces an `ALERT_ELIGIBLE` result with a complete `decision_basis` and all required fields populated.
2. A valid `SCORED_OPPORTUNITY` with score strictly below `alert_threshold` produces a `NO_ALERT` result with `suppression_reason == SCORE_BELOW_THRESHOLD`, and rules 7.2 and 7.3 are not evaluated.
3. A valid `SCORED_OPPORTUNITY` where score meets the threshold but `opportunity_status` is not in `eligible_opportunity_statuses` produces a `NO_ALERT` result with `suppression_reason == INELIGIBLE_OPPORTUNITY_STATUS`.
4. A valid `SCORED_OPPORTUNITY` where score meets the threshold and status is eligible but `duplicate_check_result == PRIOR_ALERT_EXISTS` produces a `NO_ALERT` result with `suppression_reason == DUPLICATE_ALERT_SUPPRESSED`.
5. A score exactly equal to `alert_threshold` produces `ALERT_ELIGIBLE`, confirming inclusive threshold semantics.
6. Two identical valid inputs always produce the same result with the same `alert_decision_id`.
7. An input with `scoring_result` other than `SCORED_OPPORTUNITY` produces a `PROCESSING_FAILURE` with reason `PRECONDITION_VIOLATION`.
8. An input with a missing or null `alert_threshold` produces a `PROCESSING_FAILURE` with reason `MISSING_ALERT_CONFIGURATION`.
9. An input with an `alert_threshold` outside the `score_range` produces a `PROCESSING_FAILURE` with reason `INVALID_THRESHOLD_CONFIGURATION`.
10. All three result types — `ALERT_ELIGIBLE`, `NO_ALERT`, `PROCESSING_FAILURE` — are covered by unit tests with deterministic inputs.
11. The `alert_decision_id` remains stable across retries on the same input.
12. The `decision_basis` list in every result records each rule evaluated, in the order defined in Section 7.5, with a `rule_result` of `PASSED` or `FAILED` and a `reason` for any `FAILED` entry.
13. No secret, credential, or token appears in any log output or committed configuration file.
14. The worker runs fully in a local development environment without production credentials or infrastructure.
15. A reviewer unfamiliar with this codebase can determine why an alert was or was not generated using only the `decision_basis` list, the threshold, and the status configuration — without any additional context.

---

## 15. Non-Acceptance Conditions

This worker is not acceptable if any of the following are true:

- An identical input produces different decisions across runs.
- An alert threshold or eligible status list is hardcoded within this worker rather than loaded from configuration.
- An `ALERT_ELIGIBLE` result is produced for a score strictly below `alert_threshold`.
- An `ALERT_ELIGIBLE` result is produced when `duplicate_check_result == PRIOR_ALERT_EXISTS`.
- An `ALERT_ELIGIBLE` result is produced when `opportunity_status` is not in `eligible_opportunity_statuses`.
- A threshold comparison uses `>` rather than `>=`, excluding scores exactly equal to the threshold.
- Rules are evaluated in an order other than that defined in Section 7.5.
- Any AI model is called at runtime to influence the eligibility decision.
- The system clock is used within this worker for any decision or timestamp purpose.
- Engagement heuristics, behavioral signals, or user-targeting logic influence the decision.
- A `PROCESSING_FAILURE` does not include both `failure_reason` and `failure_stage`.
- The `alert_decision_id` is generated randomly rather than derived deterministically from `pipeline_execution_id` and `notification_type`.
- This worker performs a database lookup to resolve duplicate status rather than consuming the pre-resolved `duplicate_check_result` input.
- An exception is swallowed and a partial or guessed decision is returned.
- Unit tests do not cover all three result classifications (`ALERT_ELIGIBLE`, `NO_ALERT`, `PROCESSING_FAILURE`).
- Unit tests do not include a case where `score == alert_threshold` to verify inclusive boundary semantics.
- Any committed file contains a secret, token, API key, or credential.
- The `decision_basis` list omits any rule that was evaluated, making the decision partially unexplainable.
