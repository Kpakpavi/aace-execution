# Opportunity Pipeline Job Contract

## 1. Purpose

This document is the authoritative contract for the Opportunity Pipeline Job — the first
end-to-end execution job in the AACE system.

It defines:

- what this job does and why it exists,
- what inputs it requires and what preconditions must be met,
- the exact ordered stages it must execute,
- what outputs it must produce,
- how it must behave under failure,
- what it must never do.

This is not an implementation document.
It does not contain code, pseudocode, or framework-specific instructions.
It defines the behavioral contract that implementation must satisfy.

---

## 2. Relationship to Spec Repo

This job implements behavior defined in the following AACE spec directives:

- `directives/spec/00_overview.md` — MVP objective and core data flow
- `directives/spec/01_requirements.md` — functional requirements for ingestion, detection, and scoring
- `directives/spec/06_architecture.md` — three-layer model, pipeline data flow, and domain responsibilities
- `directives/spec/12_autonomous_execution_constraints.md` — execution boundary rules and idempotency constraints
- `directives/spec/features/price_monitoring/` — discrepancy detection rules and failure modes
- `directives/spec/features/opportunity_scoring/` — scoring requirements and acceptance criteria
- `directives/spec/features/alerts/` — alert eligibility rules and notification requirements
- `directives/adr/0005_background_jobs_and_queue.md` — job design rules

This job must never redefine the business rules those directives establish.
If a rule is missing, ambiguous, or in conflict, implementation must stop and the spec must be updated first.

Business rules flow one direction: spec → this job.

---

## 3. Job Objective

The Opportunity Pipeline Job is the first complete execution of the AACE core loop.

Its objective is to take a single prepared input context — representing one product and its
observed prices across one or more sources — and produce a deterministic, structured result
indicating whether a scored arbitrage opportunity exists.

The job must:

- validate the input completely before any processing begins,
- evaluate whether a discrepancy is eligible for detection,
- detect any discrepancy present using explicit spec-defined rules,
- score any detected discrepancy using explicit spec-defined factors,
- determine whether the result is eligible to trigger an alert,
- produce a structured result representing the full outcome,
- emit an audit record capturing what happened and why.

The job must not make decisions beyond what the spec authorizes.
It must be runnable as a standalone, deterministic unit with no external orchestration.

---

## 4. Trigger Conditions

For the MVP, this job is triggered manually or by an upstream scheduling mechanism that
is outside the scope of this contract.

This job makes no assumptions about what triggered it.

The job is ready to execute when:

- a valid input context has been prepared and passed to it,
- the required preconditions are satisfied (see Section 6),
- no other instance of this job is processing the same input identity (see Section 12).

This contract does not define scheduling frequency, cron expressions, or queue configuration.
Those concerns are deferred and governed by a separate contract.

---

## 5. Required Inputs

The job requires a single structured input context containing the following:

**Product Identity**
- A stable product identifier linking to an existing product record in the system of record.

**Price Observations**
- Two or more price observations for the same product, each from a distinct source.
- Each observation must include: source identifier, observed price, observation timestamp.
- Observations must fall within the freshness window defined in the spec.

**Evaluation Context**
- The discrepancy rule set to apply, as defined in the spec.
- The scoring factor set to apply, as defined in the spec.
- The alert eligibility threshold, as defined in the spec.

No input field may be inferred, defaulted silently, or invented by the job.
If a required field is absent, the job must reject the input at validation with a structured error.

---

## 6. Preconditions

The following preconditions must be satisfied before the job begins processing.
If any precondition is not met, the job must halt with a structured precondition failure — not proceed.

1. The product referenced by the input exists in the system of record.
2. All observations reference a known, supported source identifier.
3. All observation timestamps fall within the freshness window defined by the spec.
4. At least two distinct source observations exist for the product in the input.
5. The discrepancy rule set is non-empty and has been loaded successfully.
6. The scoring factor set is non-empty and has been loaded successfully.
7. No existing opportunity record for the same input identity has already been finalized in the current run window (idempotency guard).

A precondition failure is not a processing error.
It is a structural rejection that must be logged and returned as a structured precondition failure result.

---

## 7. Execution Stages

The job executes the following eight stages in strict order.
No stage may begin before the previous stage has completed successfully.
A failure at any stage terminates the job for that input with a structured failure result.

### Stage 1 — Validate Input

Confirm that all required input fields are present, correctly typed, and within allowed value ranges.

This stage applies validation rules defined in the spec.
It does not transform data.
It does not apply business logic.
A validation failure must produce a structured rejection identifying the field and the reason.

### Stage 2 — Normalize and Prepare Input Context

Transform the validated input into the canonical internal form required by downstream stages.

This stage resolves source identifiers to their canonical representation, normalizes price values
to a consistent unit and precision, and organizes observations into the comparison structure
expected by the discrepancy detection stage.

This stage must not apply business rules. It prepares data — it does not evaluate it.

### Stage 3 — Evaluate Discrepancy Eligibility

Determine whether the normalized input context meets the preconditions required to attempt
discrepancy detection.

Eligibility criteria are defined in the spec and include:
- minimum number of observations with sufficient freshness,
- observation spread across distinct sources,
- no disqualifying flags on the product or source records.

If the context is ineligible, the job must exit with a structured no-op result.
This is not a failure. It is a valid, expected outcome.

### Stage 4 — Detect Discrepancy

Apply the spec-defined discrepancy rules to the eligible normalized context.

This stage compares price observations across sources according to the configured rule set and
determines whether a meaningful price discrepancy exists.

The detection result must include:
- whether a discrepancy was detected (boolean),
- the rule applied,
- the input values compared,
- the computed discrepancy magnitude,
- the threshold used.

If no discrepancy is detected, the job must exit with a structured no-opportunity result.
This is not a failure. It is a valid, expected outcome.

### Stage 5 — Score Opportunity

Apply the spec-defined scoring factors to the detected discrepancy.

This stage produces a numeric score representing the relative priority of this opportunity.
The score must be computed using only the factors and weights defined in the spec.
No scoring factor may be invented, adjusted, or approximated here.

The scoring result must include:
- the computed score,
- each factor applied and its individual contribution,
- the total weight used.

### Stage 6 — Decide Alert Eligibility

Evaluate whether the scored opportunity meets the alert eligibility threshold defined in the spec.

This stage does not send an alert.
It determines whether the opportunity qualifies for an alert and records that determination.

The alert eligibility result must include:
- whether the opportunity meets the threshold (boolean),
- the threshold value applied,
- the score compared against it.

### Stage 7 — Produce Structured Result

Assemble the complete structured result for this job execution.

The result must consolidate all prior stage outputs into a single structured object representing
the full outcome of the pipeline for this input context.

Result must include:
- the input identity,
- validation outcome,
- eligibility outcome,
- discrepancy detection outcome,
- scoring outcome,
- alert eligibility outcome,
- overall result classification (see Section 9),
- a timestamp marking when the result was produced.

### Stage 8 — Emit Audit and Log Outcome

Write an audit record to the system of record and emit a structured log entry capturing the
full outcome of this pipeline execution.

The audit record must be written regardless of outcome — including no-op results and failures.
A pipeline execution with no audit record is not a complete execution.

---

## 8. Stage Output Expectations

Each stage must produce an explicit, structured output before the next stage begins.

| Stage | Expected Output |
|---|---|
| 1 — Validate Input | Validated input context or structured validation rejection |
| 2 — Normalize | Normalized input context in canonical internal form |
| 3 — Evaluate Eligibility | Eligibility decision with reason |
| 4 — Detect Discrepancy | Detection result with rule, values, magnitude, and threshold |
| 5 — Score Opportunity | Score result with per-factor breakdown |
| 6 — Alert Eligibility | Alert eligibility decision with threshold and score |
| 7 — Produce Result | Complete structured pipeline result |
| 8 — Audit / Log | Confirmed audit record write and log emission |

No stage may return an implicit or ambiguous output.
A stage that cannot produce its expected output must raise an explicit structured failure.

---

## 9. Final Outputs

Every execution of this job must produce exactly one of the following classified result types:

**VALIDATION_FAILURE**
The input did not pass validation. No processing was attempted.
The result includes: the failing field(s), the failure reason(s), and the input identity.

**PRECONDITION_FAILURE**
The input passed validation but a precondition was not satisfied. No business logic was applied.
The result includes: which precondition failed and why.

**NO_OP**
The input was valid and preconditions were met, but the context was ineligible for discrepancy detection.
No discrepancy was evaluated. No opportunity was produced.
The result includes: the eligibility decision and the reason for ineligibility.

**NO_OPPORTUNITY**
Discrepancy detection ran and found no meaningful price discrepancy.
No opportunity was scored.
The result includes: the rule applied, the values compared, and the reason detection did not produce a discrepancy.

**OPPORTUNITY_DETECTED**
A discrepancy was detected and an opportunity was scored.
The result includes: the full detection result, the score, the factor breakdown, and the alert eligibility decision.

**PROCESSING_FAILURE**
An unexpected error occurred during one of the processing stages.
The result includes: the stage where the failure occurred, the error type, and whether it is retriable.

All result types must be persisted as structured records.
All result types must produce an audit event in Stage 8.

---

## 10. Failure Modes

### Validation Failure
- Cause: missing field, wrong type, out-of-range value in the input.
- Classification: VALIDATION_FAILURE.
- Behavior: immediate halt, no processing, structured rejection returned.
- Retriable: no — the input must be corrected before resubmission.

### Precondition Failure
- Cause: a required precondition is not satisfied (e.g., stale observations, missing product record).
- Classification: PRECONDITION_FAILURE.
- Behavior: halt before business logic begins, structured rejection returned.
- Retriable: depends on the precondition — stale observations may become fresh; a missing product record is terminal.

### Eligibility No-Op
- Cause: valid input but context does not meet eligibility criteria for detection.
- Classification: NO_OP.
- Behavior: clean exit, structured no-op result returned. Not an error.
- Retriable: not applicable — the result is correct for this input.

### No Discrepancy
- Cause: detection ran successfully but no meaningful discrepancy was found.
- Classification: NO_OPPORTUNITY.
- Behavior: clean exit, structured no-opportunity result returned. Not an error.
- Retriable: not applicable — the result is correct for this input.

### Transient Processing Failure
- Cause: temporary unavailability of the system of record or an external dependency.
- Classification: PROCESSING_FAILURE.
- Behavior: explicit exception raised, failure logged, retry eligible up to the configured retry limit.
- Retriable: yes, with bounded retry count.

### Terminal Processing Failure
- Cause: an unrecoverable error within a processing stage (e.g., corrupt normalized context, rule set load failure).
- Classification: PROCESSING_FAILURE.
- Behavior: explicit exception raised, failure logged, no retry.
- Retriable: no — must be diagnosed and corrected before rerunning.

---

## 11. Retry Rules

1. Only PROCESSING_FAILURE results classified as transient are eligible for retry.
2. The maximum retry count is defined in configuration. It must not be hardcoded.
3. Each retry attempt must be individually logged with attempt number and outcome.
4. After the retry limit is exceeded, the failure must be escalated as a terminal failure.
5. VALIDATION_FAILURE and PRECONDITION_FAILURE results must never be retried automatically.
6. NO_OP and NO_OPPORTUNITY results must never be retried — they are correct outcomes.
7. A retry must re-execute the full pipeline from Stage 1, not from the stage that failed.
8. Retried executions must not produce duplicate audit records for stages completed before the failure.

---

## 12. Idempotency Rules

1. Running this job multiple times on the same input identity must not create duplicate opportunity records.
2. Running this job multiple times on the same input identity must not create duplicate audit records for the same execution instance.
3. Each execution must carry a unique execution identifier that is used for deduplication at the persistence layer.
4. If a job for a given input identity is already in a finalized state (OPPORTUNITY_DETECTED, NO_OPPORTUNITY, NO_OP), a rerun must detect this via the idempotency guard in Precondition 7 and exit without reprocessing.
5. If a job for a given input identity failed mid-run (PROCESSING_FAILURE), a rerun is permitted and must resume as a clean execution from Stage 1.
6. Idempotency behavior must be verified by tests that assert record counts remain stable after multiple runs on the same input.

---

## 13. Logging and Audit Requirements

### Logging Requirements

Every execution of this job must emit a structured log entry at each of the following points:

- job start: input identity, execution identifier, timestamp
- each stage start and completion: stage name, outcome classification
- any failure: failure type, stage, error context, retriable status
- job end: final result classification, total execution duration

Logs must be structured and machine-readable.
Logs must never include secrets, credentials, tokens, or raw passwords.
Logs must never include full external API response payloads that may contain sensitive data.

### Audit Requirements

- An audit record must be written to the system of record for every job execution, regardless of outcome.
- The audit record must include: input identity, execution identifier, result classification, timestamp, and stage-level outcome summary.
- For OPPORTUNITY_DETECTED results, the audit record must also include: the discrepancy rule applied, the score, and the alert eligibility decision.
- For PROCESSING_FAILURE results, the audit record must include: the stage of failure and the error classification.
- Audit records must be written in Stage 8. A pipeline that completes Stage 7 but fails to write an audit record is not a successfully completed execution.

---

## 14. What This Job Must NOT Do

The following are explicitly forbidden in this job:

- **Redefine business rules.** Discrepancy thresholds, scoring factors, eligibility criteria, and alert thresholds are owned by the spec. This job applies them — it does not set them.
- **Make AI-driven runtime decisions.** No AI model may be called to determine eligibility, detect discrepancies, compute scores, or decide alert eligibility. All logic is deterministic and code-defined.
- **Send alerts or notifications.** Stage 6 decides eligibility only. Sending alerts is a downstream concern outside this job's scope.
- **Write to a production database during test execution.** Tests must use isolated, controlled persistence.
- **Emit partial results on failure.** A failed pipeline must not persist a partial OPPORTUNITY_DETECTED record.
- **Silently swallow errors.** Every failure must surface as a structured result with a classification.
- **Operate on more than one input identity per execution.** This job processes one input context per run.
- **Apply rules not present in the loaded rule set.** If a rule is not in the configured rule set, it does not apply.
- **Assume freshness.** Observation timestamps must be explicitly checked against the spec-defined freshness window. Recency must never be assumed.
- **Proceed past a failed stage.** If any stage fails, subsequent stages must not execute.

---

## 15. Success Criteria

This job is successful when:

1. A valid input with a detectable discrepancy produces an OPPORTUNITY_DETECTED result with a complete score and factor breakdown.
2. A valid input with no discrepancy produces a NO_OPPORTUNITY result with the rule applied and comparison values recorded.
3. An ineligible input context produces a NO_OP result with the eligibility reason recorded.
4. An invalid input produces a VALIDATION_FAILURE result identifying the field and reason without executing any business logic.
5. An unsatisfied precondition produces a PRECONDITION_FAILURE result without executing any pipeline stages.
6. A transient failure retries up to the configured limit before escalating as a terminal PROCESSING_FAILURE.
7. All six result types are covered by unit tests with deterministic inputs.
8. Rerunning the job on the same finalized input produces no duplicate records.
9. Every execution produces an audit record, including no-op and failure outcomes.
10. Every OPPORTUNITY_DETECTED result is fully traceable to its source observations, the rule applied, and the scoring factors used.
11. No secrets appear in any log output or committed configuration.
12. The job runs fully in a local development environment without production credentials or infrastructure.

---

## 16. Non-Acceptance Conditions

This job is not acceptable if any of the following are true:

- Any stage proceeds after a prior stage has failed.
- A discrepancy rule or scoring factor is defined within this job rather than loaded from the spec-defined configuration.
- An AI model is called at runtime to determine any business outcome.
- A successful pipeline execution produces no audit record.
- Rerunning the job on the same input creates duplicate opportunity records.
- An invalid input reaches Stage 3 or beyond without first passing validation in Stage 1.
- A PROCESSING_FAILURE does not include the stage of failure and whether it is retriable.
- An OPPORTUNITY_DETECTED result cannot be traced to its source observations and scoring factors.
- Any secret, credential, or token appears in a committed file or structured log output.
- Unit tests do not cover all six result classifications.
- Any failure mode is handled by silent exception swallowing or an implicit empty return.

Any of these conditions is a blocking defect.
The job must not be considered complete while any non-acceptance condition is present.
