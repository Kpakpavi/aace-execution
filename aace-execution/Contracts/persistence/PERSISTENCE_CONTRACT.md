# Persistence Contract

## 1. Purpose

This document is the authoritative contract for the persistence layer of the AACE execution
project.

It defines:

- what data must be persisted and when,
- the required fields for each persisted record type,
- the rules governing write timing, idempotency, and failure handling,
- the auditability and determinism guarantees the persistence layer must satisfy,
- what the persistence layer is and is not allowed to do.

This is not an implementation document.
It does not contain code, pseudocode, or framework-specific instructions.
It does not choose a storage technology, database engine, or serialization format.
It defines the behavioral contract that any persistence implementation must satisfy.

---

## 2. Relationship to Spec Repo

This contract implements persistence requirements defined in the following AACE spec directives:

- `directives/spec/06_architecture.md` — three-layer model, pipeline data flow, persistence
  responsibilities
- `directives/spec/12_autonomous_execution_constraints.md` — execution boundary rules,
  idempotency constraints, auditability requirements
- `directives/spec/03_constraints.md` — non-negotiable system constraints including traceability
  and determinism
- `execution/README.md` — execution layer contract and persistence expectations

This contract also serves the persistence needs defined by the following execution contracts:

- `EXECUTION_CONTRACT.md` — Section 5 (execution rules requiring audit events on every state
  write), Section 6 (output rules requiring persistence before return), Section 8 (idempotency
  rules)
- `PIPELINE_ORCHESTRATION_CONTRACT.md` — Section 4 (orchestrator does not persist directly;
  persistence consumes the assembled result), Section 6 Stage 6 (audit record emission),
  Section 12 (idempotency at the persistence layer)
- `OPPORTUNITY_PIPELINE_JOB.md` — Section 9 (all result types must be persisted as structured
  records), Section 12 (idempotency rules), Section 13 (audit requirements)
- `SCORING_WORKER_CONTRACT.md` — Section 8 (scoring output structure that must be persisted
  downstream)
- `ALERT_DECISION_CONTRACT.md` — Section 8 (alert decision output structure that must be
  persisted downstream)
- `DISCREPANCY_WORKER_CONTRACT.md` — Section 8 (discrepancy output structure referenced by
  downstream persistence)

Business rules and persistence requirements flow one direction: spec and stage contracts →
this persistence contract.
This contract must not redefine any rule owned by those contracts or directives.

---

## 3. Persistence Objective

The persistence layer is responsible for durably recording the outputs of the AACE Opportunity
Pipeline so that every pipeline execution is recoverable, traceable, and auditable after the
fact.

Its objective is to:

- accept the assembled pipeline result produced by the orchestrator's Stage 5,
- write each required record type to the system of record,
- enforce idempotency so that duplicate writes for the same `pipeline_execution_id` do not
  create duplicate records,
- ensure that audit records are written for every pipeline execution regardless of outcome,
- ensure that no pipeline execution is reported as complete until all required persistence
  writes have succeeded.

The persistence layer makes no business decisions.
It writes what the pipeline produced — it does not evaluate, transform, or supplement it.

---

## 4. Persistence Scope

### In Scope

The persistence layer is responsible for writing the following record types to the system
of record:

1. Pipeline result records
2. Opportunity records
3. Alert decision records
4. Audit records

### Out of Scope

The persistence layer does not:

- execute pipeline stages or invoke workers,
- evaluate business rules (discrepancy detection, scoring, alert eligibility),
- send or schedule notifications,
- fetch or enrich data from external sources,
- define the structure of pipeline outputs — it consumes them as defined by the stage contracts,
- choose when to run — it is invoked by the pipeline orchestrator or job layer after Stage 5
  assembly.

---

## 5. Records That Must Be Persisted

The following record types must be written to the system of record. Each record type has
mandatory and conditional persistence rules.

### 5.1 Pipeline Result Record

**When written**: For every pipeline execution, regardless of final result classification.

This is the canonical record of what the pipeline produced for a given `pipeline_execution_id`.

**Mandatory on all paths**: Yes. A pipeline execution without a persisted result record is
incomplete.

This record must be written for all seven result classifications:
`OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`, `NO_OPPORTUNITY`, `NO_OP`,
`VALIDATION_FAILURE`, `PRECONDITION_FAILURE`, `PROCESSING_FAILURE`.

### 5.2 Opportunity Record

**When written**: Only when the pipeline produces an `OPPORTUNITY_DETECTED` or
`OPPORTUNITY_SCORED_NO_ALERT` result.

This record captures the scored opportunity including the discrepancy that produced it,
the score and factor breakdown, and the alert eligibility decision.

**Mandatory on failure paths**: No. An opportunity record must not be written for
`VALIDATION_FAILURE`, `PRECONDITION_FAILURE`, `NO_OPPORTUNITY`, `NO_OP`, or
`PROCESSING_FAILURE` results. Writing an opportunity record for a non-opportunity result
is a persistence defect.

### 5.3 Alert Decision Record

**When written**: Only when the pipeline reaches Stage 4 and produces an `ALERT_ELIGIBLE`
or `NO_ALERT` decision.

This record captures the alert eligibility evaluation including the decision basis,
threshold applied, and suppression reason (if `NO_ALERT`).

**Mandatory on failure paths**: No. An alert decision record must not be written if the
pipeline halted before Stage 4 completed. Writing an alert decision record for a pipeline
that never reached Stage 4 is a persistence defect.

### 5.4 Audit Record

**When written**: For every pipeline execution, regardless of final result classification.

This is the mandatory trail record that captures what happened, when, and why for a given
pipeline execution.

**Mandatory on all paths**: Yes — including `NO_OP`, `VALIDATION_FAILURE`,
`PRECONDITION_FAILURE`, and `PROCESSING_FAILURE` outcomes. A pipeline execution without
a persisted audit record is incomplete, even if all other records were written successfully.

**Mandatory even on persistence failure paths**: Yes. If writing the pipeline result record
or opportunity record fails, the audit record must still be attempted. The audit record must
capture the persistence failure itself as part of its content. See Section 9 for details.

---

## 6. Required Fields Per Record Type

### 6.1 Pipeline Result Record

| Field | Type | Description |
|---|---|---|
| `pipeline_execution_id` | string | The unique identifier for this pipeline run. Primary deduplication key. |
| `product_id` | string | Stable product identifier from the pipeline input context. |
| `result_classification` | string | One of the seven result classifications defined in `PIPELINE_ORCHESTRATION_CONTRACT.md` Section 8. |
| `stage_reached` | string | The last pipeline stage that executed before the result was assembled. |
| `result_timestamp` | string | ISO 8601 timestamp marking when the result was assembled. Must be the `freshness_reference_timestamp` carried through the pipeline, not derived from the system clock at write time. |
| `stage_outcome_summary` | object | A structured summary listing each stage that executed and its output classification. |
| `retry_eligible` | boolean | For `PROCESSING_FAILURE` results: whether the failure is retriable. Null for non-failure results. |
| `failure_stage` | string or null | For `PROCESSING_FAILURE` results: which stage failed. Null for non-failure results. |
| `failure_reason` | string or null | For `PROCESSING_FAILURE` results: the classified failure reason. Null for non-failure results. |

### 6.2 Opportunity Record

| Field | Type | Description |
|---|---|---|
| `pipeline_execution_id` | string | Links this opportunity to the pipeline run that produced it. Primary deduplication key. |
| `product_id` | string | Stable product identifier. |
| `pair_id` | string | The canonical pair identifier from the discrepancy that produced this opportunity. |
| `result_classification` | string | `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT`. |
| `discrepancy_rule_id` | string | The discrepancy rule applied. |
| `discrepancy_source_a` | string | Canonical source identifier A. |
| `discrepancy_source_b` | string | Canonical source identifier B. |
| `price_a` | number | Normalized price from source A. |
| `price_b` | number | Normalized price from source B. |
| `absolute_difference` | number | Computed absolute price difference. |
| `percentage_difference` | number | Computed percentage price difference. |
| `score` | number | The final computed opportunity score. |
| `score_result_id` | string | Deterministic scoring result identifier. |
| `scoring_factors_applied` | list | The full factor breakdown from the scoring worker output. |
| `score_range` | object | The configured min and max of the scoring range. |
| `alert_decision` | string | `ALERT_ELIGIBLE` or `NO_ALERT`. |
| `alert_decision_id` | string | Deterministic alert decision identifier. |
| `suppression_reason` | string or null | For `NO_ALERT`: the reason the alert was suppressed. Null for `ALERT_ELIGIBLE`. |
| `opportunity_timestamp` | string | ISO 8601 timestamp. Must be the `freshness_reference_timestamp` carried through the pipeline. |

### 6.3 Alert Decision Record

| Field | Type | Description |
|---|---|---|
| `pipeline_execution_id` | string | Links this decision to the pipeline run. Primary deduplication key together with `notification_type`. |
| `alert_decision_id` | string | Deterministic identifier derived from `pipeline_execution_id` and `notification_type`. |
| `product_id` | string | Stable product identifier. |
| `pair_id` | string | The canonical pair identifier. |
| `score` | number | The score evaluated against the threshold. |
| `alert_threshold` | number | The configured threshold applied. |
| `threshold_met` | boolean | Whether the score met or exceeded the threshold. |
| `decision_result` | string | `ALERT_ELIGIBLE` or `NO_ALERT`. |
| `suppression_reason` | string or null | For `NO_ALERT`: the primary suppression reason. Null for `ALERT_ELIGIBLE`. |
| `decision_basis` | list | Ordered list of rule evaluations from the alert decision worker. |
| `notification_type` | string | The notification condition type evaluated. |
| `duplicate_check_result` | string | The pre-resolved duplicate check value: `NO_PRIOR_ALERT` or `PRIOR_ALERT_EXISTS`. |
| `decision_reference_timestamp` | string | ISO 8601 timestamp from the alert decision worker input. |

### 6.4 Audit Record

| Field | Type | Description |
|---|---|---|
| `pipeline_execution_id` | string | The unique identifier for the pipeline run this audit record describes. |
| `product_id` | string | Stable product identifier. |
| `result_classification` | string | The final result classification of the pipeline execution. |
| `result_timestamp` | string | ISO 8601 timestamp of result assembly. |
| `stage_outcome_summary` | object | Each stage that executed and its output classification. |
| `discrepancy_rule_applied` | string or null | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the rule ID. Null otherwise. |
| `score` | number or null | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the computed score. Null otherwise. |
| `scoring_factor_summary` | list or null | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the factor breakdown. Null otherwise. |
| `alert_decision` | string or null | For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT`: the alert eligibility decision. Null otherwise. |
| `failure_stage` | string or null | For `PROCESSING_FAILURE`: the stage where the failure occurred. Null otherwise. |
| `failure_reason` | string or null | For `PROCESSING_FAILURE`: the classified failure reason. Null otherwise. |
| `early_exit_stage` | string or null | For `NO_OP` and `NO_OPPORTUNITY`: the stage at which the pipeline exited early. Null otherwise. |
| `early_exit_reason` | string or null | For `NO_OP` and `NO_OPPORTUNITY`: the reason for early exit. Null otherwise. |
| `persistence_outcome` | string | Whether all other persistence writes for this execution succeeded. One of: `ALL_WRITES_SUCCEEDED`, `PARTIAL_WRITE_FAILURE`, `RESULT_WRITE_FAILED`. |
| `persistence_failure_detail` | string or null | If any persistence write failed, a description of which write failed and why. Null if all writes succeeded. |
| `audit_written_at` | string | ISO 8601 timestamp of when this audit record was written. This is the one field permitted to use the actual write time, because the audit record documents the persistence event itself. |

---

## 7. Write Timing Rules

The following rules govern when persistence writes occur relative to pipeline execution.

1. **No writes during pipeline execution.** The persistence layer must not write any record
   while pipeline stages 1 through 4 are executing. Persistence writes occur after the
   orchestrator has assembled the Stage 5 result and emitted the Stage 6 audit event.

2. **Write order is fixed.** When a pipeline execution requires multiple record types, writes
   must occur in this order:
   1. Pipeline result record
   2. Opportunity record (if applicable)
   3. Alert decision record (if applicable)
   4. Audit record (always last)

   The audit record is written last because it must capture the outcome of all preceding writes
   in its `persistence_outcome` field.

3. **All writes for one execution must complete before returning success.** The pipeline
   execution is not complete until all required writes for its result classification have
   succeeded. A pipeline that assembled its result but failed to persist it is not a successful
   execution.

4. **Audit record write must be attempted even if earlier writes fail.** If the pipeline result
   record or opportunity record write fails, the persistence layer must still attempt to write
   the audit record documenting the failure. See Section 9.

5. **No deferred or asynchronous writes.** All persistence writes must be synchronous and
   confirmed before the pipeline execution returns its result to the caller. A write that is
   enqueued but not confirmed is not a completed write.

6. **No speculative writes.** The persistence layer must not write records based on intermediate
   stage outputs. It writes only from the assembled Stage 5 result. A partially assembled result
   must never be persisted.

---

## 8. Idempotency Rules

1. **`pipeline_execution_id` is the primary deduplication key.** Every record type uses
   `pipeline_execution_id` (alone or in combination with `notification_type` for alert decision
   records) as the key for idempotency enforcement.

2. **Duplicate writes must not create duplicate records.** If a persistence write is attempted
   for a `pipeline_execution_id` that already has a finalized record of the same type, the write
   must be rejected or ignored — it must not create a second record.

3. **Idempotency enforcement must be at the persistence layer.** The persistence layer must
   enforce unique constraints on the deduplication key. It must not rely solely on the caller
   checking before writing. The persistence layer is the last line of defense against duplicates.

4. **Retried pipeline executions carry the same `pipeline_execution_id`.** When a pipeline is
   retried after a `PROCESSING_FAILURE`, it uses the same `pipeline_execution_id`. The
   persistence layer must handle this correctly:
   - If no prior record exists for this `pipeline_execution_id`, write normally.
   - If a prior `PROCESSING_FAILURE` result record exists, the new write must replace or
     supersede it — a successful retry must not be blocked by a prior failure record.
   - If a prior finalized record exists (`OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`,
     `NO_OPPORTUNITY`, `NO_OP`), the write must be rejected. A finalized result must not be
     overwritten.

5. **Audit records are append-only.** Unlike other record types, audit records are not
   deduplicated. Each pipeline execution attempt (including retries) must produce its own audit
   record. Multiple audit records for the same `pipeline_execution_id` are expected when retries
   occur.

6. **Idempotency must be verified by tests.** Tests must assert that:
   - writing the same result twice for the same `pipeline_execution_id` does not increase
     record counts,
   - a successful retry after a `PROCESSING_FAILURE` updates the result record,
   - a retry after a finalized result is rejected,
   - audit records accumulate across retries.

---

## 9. Failure Handling

### 9.1 Pipeline Result Record Write Failure

- **Impact**: The pipeline execution cannot be reported as complete.
- **Behavior**: The persistence layer must surface this failure explicitly. It must not be
  suppressed.
- **Audit**: The audit record must still be attempted. The audit record's `persistence_outcome`
  must be set to `RESULT_WRITE_FAILED` with `persistence_failure_detail` describing the failure.
- **Caller notification**: The pipeline execution must return a failure status to the caller
  indicating that persistence failed.

### 9.2 Opportunity Record Write Failure

- **Impact**: The pipeline result was persisted but the opportunity detail was not.
- **Behavior**: The persistence layer must surface this failure explicitly.
- **Audit**: The audit record must still be attempted. The audit record's `persistence_outcome`
  must be set to `PARTIAL_WRITE_FAILURE` with detail identifying which write failed.
- **Caller notification**: The pipeline execution must return a failure status indicating
  partial persistence.

### 9.3 Alert Decision Record Write Failure

- **Impact**: The pipeline result and opportunity were persisted but the alert decision was not.
- **Behavior**: Same as Section 9.2. The persistence layer must surface this failure explicitly.
- **Audit**: The audit record must capture the partial failure.

### 9.4 Audit Record Write Failure

- **Impact**: Critical. The audit trail for this pipeline execution is broken.
- **Behavior**: The persistence layer must surface this failure as an explicit error. An audit
  write failure must never be silently suppressed.
- **Caller notification**: The pipeline execution must be treated as incomplete even if all
  other writes succeeded. A pipeline execution without an audit record is not complete.
- **Escalation**: Audit write failures must be logged at the highest severity level available.
  Repeated audit write failures indicate a systemic issue that must be investigated.

### 9.5 Transient vs. Terminal Persistence Failures

- **Transient failures** (e.g., temporary unavailability of the storage system): may be retried
  at the persistence layer with bounded retry count. Each retry attempt must be logged.
- **Terminal failures** (e.g., constraint violation indicating a logic error, schema mismatch):
  must not be retried. They must be surfaced immediately with diagnostic context.
- The persistence layer must distinguish between transient and terminal failures in its error
  reporting.

---

## 10. Auditability Requirements

1. **Every pipeline execution must have an audit record.** There is no exception to this rule.
   `NO_OP`, `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`, and `PROCESSING_FAILURE` outcomes
   must produce audit records just as `OPPORTUNITY_DETECTED` outcomes do.

2. **Audit records must be self-contained.** A reviewer must be able to understand what happened
   in a pipeline execution by reading its audit record alone, without needing to query other
   record types. The audit record must contain the result classification, the stages that
   executed, the key decision points, and any failure information.

3. **Audit records must capture persistence outcomes.** The audit record must document whether
   all persistence writes for this execution succeeded, partially failed, or failed entirely.
   This makes the audit trail self-referentially complete.

4. **Audit records must not be modified after write.** Once an audit record has been persisted,
   it must not be updated, overwritten, or deleted. Audit records are append-only and immutable
   after creation.

5. **Audit records must support traceability.** For `OPPORTUNITY_DETECTED` and
   `OPPORTUNITY_SCORED_NO_ALERT` results, the audit record must contain enough information
   to trace the outcome back to its source observations, the discrepancy rule applied, the
   scoring factors used, and the alert eligibility decision — without requiring access to the
   opportunity record.

6. **Audit records must be queryable by `pipeline_execution_id`.** The persistence layer must
   support retrieving all audit records for a given `pipeline_execution_id`, including multiple
   records from retry attempts.

---

## 11. Determinism Rules

1. **Same assembled result → same persisted records.** Given the same Stage 5 assembled result,
   the persistence layer must produce the same set of records with the same field values on
   every execution. No field value may vary between runs for the same input, with the sole
   exception of `audit_written_at` (which documents the actual write event time).

2. **No derived or computed fields.** The persistence layer must not compute, derive, or
   transform any field value from the assembled result. It persists what the pipeline produced.
   If a field needs to exist in the persisted record, it must be present in the assembled result.

3. **No conditional field population based on runtime state.** The persistence layer must not
   populate fields differently based on system load, time of day, storage capacity, or any other
   runtime condition. Field population is determined solely by the assembled result content and
   the record type requirements defined in Section 6.

4. **No system-clock-derived timestamps in business records.** All timestamps in pipeline result
   records, opportunity records, and alert decision records must originate from the pipeline's
   `freshness_reference_timestamp`. The persistence layer must not substitute the system clock.
   The only exception is `audit_written_at` in the audit record, which documents the persistence
   event itself.

5. **Record content must not depend on write order.** Although writes occur in a defined order
   (Section 7 Rule 2), the content of each record must not depend on whether earlier records
   were already written. Each record's content is determined entirely by the assembled pipeline
   result.

6. **No random identifiers at the persistence layer.** All record identifiers
   (`pipeline_execution_id`, `score_result_id`, `alert_decision_id`, `pair_id`) are generated
   upstream by the pipeline. The persistence layer must use these identifiers as provided. It
   must not generate, replace, or supplement them.

---

## 12. What Persistence Must NOT Do

The following are explicitly forbidden in the persistence layer:

- **Evaluate business rules.** The persistence layer does not determine whether a discrepancy
  exists, how to score an opportunity, or whether an alert is eligible. It writes the results
  of those evaluations.
- **Transform or enrich data.** The persistence layer writes what it receives. It must not
  add, modify, or remove fields from the assembled result before writing.
- **Make write-or-skip decisions based on business logic.** Whether a record should be written
  is determined by the result classification and the rules in Section 5 — not by evaluating
  the business content of the result.
- **Call external APIs or services.** The persistence layer writes to the system of record.
  It does not call marketplace APIs, notification services, or any external system.
- **Send or schedule notifications.** Persistence of an `ALERT_ELIGIBLE` decision does not
  trigger notification delivery. Notification delivery is a downstream concern outside
  this contract.
- **Delete or overwrite finalized records.** A finalized pipeline result
  (`OPPORTUNITY_DETECTED`, `OPPORTUNITY_SCORED_NO_ALERT`, `NO_OPPORTUNITY`, `NO_OP`) must
  not be deleted or overwritten by a subsequent write. See Section 8 Rule 4.
- **Suppress audit record writes.** The audit record must be attempted for every pipeline
  execution. No failure in other record writes justifies skipping the audit record.
- **Use AI models at runtime.** No AI model may be invoked within the persistence layer for
  any purpose — not for data transformation, validation, deduplication, or any other operation.
- **Generate timestamps from the system clock for business records.** All business-record
  timestamps must originate from the pipeline. The sole exception is `audit_written_at`.
- **Silently swallow write failures.** Every write failure must be surfaced explicitly and
  captured in the audit record.
- **Write partial records.** A record must be written completely or not at all. A partially
  written record (e.g., an opportunity record missing its scoring factors) is a persistence
  defect.
- **Couple record writes across pipeline executions.** Each pipeline execution's persistence
  writes are independent. The persistence layer must not batch, merge, or correlate records
  from different `pipeline_execution_id` values in a single write operation.

---

## 13. Success Criteria

The persistence layer is successful when:

1. Every pipeline execution — regardless of result classification — produces a persisted
   pipeline result record and a persisted audit record.
2. `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT` results produce a persisted
   opportunity record containing the full discrepancy reference, score breakdown, and alert
   decision.
3. Pipeline executions that reach Stage 4 produce a persisted alert decision record containing
   the decision basis and threshold evaluation.
4. Writing the same result twice for the same `pipeline_execution_id` does not create duplicate
   records (idempotency verified).
5. A successful retry after a `PROCESSING_FAILURE` updates the pipeline result record and does
   not create a duplicate.
6. A retry after a finalized result is rejected without modifying the existing record.
7. Audit records accumulate across retries — each attempt produces its own audit record.
8. A persistence failure in the pipeline result record or opportunity record still results in
   an audit record documenting the failure.
9. An audit write failure is surfaced as an explicit error and the pipeline execution is
   treated as incomplete.
10. No opportunity record is written for `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`,
    `NO_OPPORTUNITY`, `NO_OP`, or `PROCESSING_FAILURE` results.
11. No alert decision record is written for pipeline executions that did not reach Stage 4.
12. All persisted records are traceable to their source pipeline execution via
    `pipeline_execution_id`.
13. For `OPPORTUNITY_DETECTED` and `OPPORTUNITY_SCORED_NO_ALERT` results, a reviewer can trace
    the full path from source observations through discrepancy detection, scoring, and alert
    decision using only the persisted records.
14. No secret, credential, or token appears in any persisted record.
15. The persistence layer runs fully in a local development environment without production
    credentials or infrastructure.
16. All record types and all result classifications are covered by persistence tests with
    deterministic inputs.

---

## 14. Non-Acceptance Conditions

The persistence layer is not acceptable if any of the following are true:

- A pipeline execution completes without a persisted pipeline result record.
- A pipeline execution completes without a persisted audit record.
- An `OPPORTUNITY_DETECTED` or `OPPORTUNITY_SCORED_NO_ALERT` result has no corresponding
  opportunity record.
- A pipeline execution that reached Stage 4 has no corresponding alert decision record.
- An opportunity record is written for a `VALIDATION_FAILURE`, `PRECONDITION_FAILURE`,
  `NO_OPPORTUNITY`, `NO_OP`, or `PROCESSING_FAILURE` result.
- An alert decision record is written for a pipeline execution that never reached Stage 4.
- Writing the same result twice for the same `pipeline_execution_id` creates duplicate records.
- A finalized pipeline result record is overwritten or deleted by a subsequent write.
- A retry after a `PROCESSING_FAILURE` is blocked by the prior failure record instead of
  superseding it.
- An audit record is modified or deleted after being written.
- A persistence write failure is silently suppressed without being captured in the audit record.
- An audit write failure is silently suppressed without surfacing an explicit error.
- The persistence layer generates or modifies business-record timestamps using the system clock.
- The persistence layer generates, replaces, or supplements record identifiers that were
  assigned upstream by the pipeline.
- The persistence layer transforms, enriches, or evaluates the content of the assembled
  pipeline result.
- An AI model is invoked within the persistence layer for any purpose.
- A partial record is written (e.g., an opportunity record without scoring factors).
- Persistence tests do not cover all four record types and all seven result classifications.
- Any persisted record contains a secret, credential, token, or API key.
- A reviewer cannot trace an `OPPORTUNITY_DETECTED` result from persisted records alone back
  to its source observations, discrepancy rule, scoring factors, and alert decision.

Any of these conditions is a blocking defect.
The persistence layer must not be considered complete while any non-acceptance condition
is present.
