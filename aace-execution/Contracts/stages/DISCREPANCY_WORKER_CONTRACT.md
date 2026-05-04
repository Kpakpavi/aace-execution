# Discrepancy Worker Contract

## 1. Purpose

This document is the authoritative contract for the AACE Discrepancy Worker.

It defines:

- what the worker is responsible for,
- what inputs it requires and what preconditions must be met,
- the exact comparison and evaluation rules it must apply,
- what it must produce as output,
- how it must behave under failure,
- what it must never do.

The Discrepancy Worker executes Stage 4 of the Opportunity Pipeline Job
(defined in `OPPORTUNITY_PIPELINE_JOB.md`). It receives a normalized input context
that has already passed validation (Stage 1) and normalization (Stage 2) and has
cleared eligibility evaluation (Stage 3). It must not be invoked unless all three
prior stages have completed successfully.

This worker produces one result: a determination of whether a meaningful price
discrepancy exists in the input context, and if so, a complete structured description
of that discrepancy.

This is not an implementation document. It contains no code, pseudocode, or
framework-specific instructions. It defines the behavioral contract that
implementation must satisfy.

---

## 2. Relationship to Spec Repo

This worker enforces rules defined in the following AACE spec directives:

- `directives/spec/features/price_monitoring/01_requirements.md` — price comparison
  requirements, eligibility conditions, threshold handling, freshness rules,
  explainability and traceability requirements
- `directives/spec/features/price_monitoring/03_discrepancy_rules.md` — exact
  discrepancy rules: absolute difference, percentage difference, threshold
  definitions, directionality, noise filtering, duplicate handling, and result
  construction requirements
- `directives/spec/features/price_monitoring/02_acceptance_criteria.md` — acceptance
  criteria for detection correctness, determinism, explainability, and
  downstream compatibility
- `directives/spec/features/price_monitoring/04_failure_modes.md` — failure
  handling requirements for invalid comparisons and evaluation errors
- `directives/spec/features/opportunity_scoring/01_requirements.md` — downstream
  compatibility requirements that discrepancy output must satisfy
- `directives/spec/12_autonomous_execution_constraints.md` — determinism,
  idempotency, and execution boundary rules

This worker must never redefine the rules those documents establish.
If a comparison rule, threshold definition, or noise filter is unclear or missing
in the spec, implementation must stop and the spec must be updated first.

Rule ownership flows one direction: spec → this worker.

---

## 3. Worker Objective

The Discrepancy Worker has one objective:

**Determine with certainty whether a meaningful price discrepancy exists across the
price observations in the normalized input context, using only the rules defined
in the spec.**

To do this it must:

- identify all valid, comparable price observation pairs from distinct sources,
- compute the absolute price difference and percentage price difference for each pair,
- evaluate each pair against the configured discrepancy rule set,
- determine whether any pair crosses the threshold that constitutes a meaningful
  discrepancy,
- apply noise filtering rules to suppress non-meaningful differences,
- produce a structured result classifying the outcome as NO_DISCREPANCY or
  DISCREPANCY_DETECTED,
- include in the result everything needed to explain, trace, and audit the evaluation.

The worker must not score opportunities.
The worker must not trigger alerts.
The worker must not fetch, modify, enrich, or persist any data.
It evaluates a prepared context and returns a result — nothing more.

---

## 4. Required Inputs

The worker receives the normalized input context produced by Stage 2 (normalization)
of the Opportunity Pipeline Job. This context has already been validated and
confirmed eligible by Stages 1 and 3.

The following fields are required in the normalized context. If any are absent when
this worker executes, that is a pipeline error, not a validation error — and the
worker must surface it as a PROCESSING_FAILURE.

### 4.1 Product Context

| Field | Type | Expectation |
|---|---|---|
| product_id | string | Non-empty. Stable canonical identifier. |
| product_name | string | Non-empty after normalization. |

### 4.2 Normalized Observations (per observation)

| Field | Type | Expectation |
|---|---|---|
| observation_id | string | Non-empty. Unique within this context. |
| source | string | Canonical source identifier. Member of allowed source set. |
| normalized_price | numeric | Canonical precision. Greater than zero. |
| observed_at | datetime | Within freshness window. Already confirmed by Stage 3. |
| listing_ref | string | References a listing in this context. |

### 4.3 Discrepancy Rule Set

| Field | Type | Expectation |
|---|---|---|
| rule_id | string | Stable identifier for the rule being applied. |
| threshold_method | string | One of: `ABSOLUTE`, `PERCENTAGE`, or `BOTH`. |
| absolute_threshold | numeric | Required when method is ABSOLUTE or BOTH. Greater than zero. |
| percentage_threshold | numeric | Required when method is PERCENTAGE or BOTH. Greater than zero. |

### 4.4 Evaluation Context

| Field | Type | Expectation |
|---|---|---|
| evaluation_reference_timestamp | datetime | The reference time for this evaluation run. Passed explicitly — not derived from system clock. |
| pipeline_execution_id | string | Stable identifier linking this evaluation to its parent pipeline run. |

---

## 5. Preconditions

The following preconditions must be satisfied before the worker begins evaluation.
These should have been confirmed by earlier pipeline stages, but the worker must
verify them before proceeding. A failed precondition surfaces as a PROCESSING_FAILURE,
not a new validation failure.

1. The normalized input context contains at least two observations with distinct
   source identifiers.
2. All observations reference valid listings within the context.
3. All normalized prices are strictly greater than zero.
4. The discrepancy rule set is non-null, non-empty, and contains at least one
   configured threshold.
5. The `evaluation_reference_timestamp` is present and is a valid datetime.
6. The `pipeline_execution_id` is present and non-empty.

If any precondition fails, the worker must halt with a PROCESSING_FAILURE result
describing which precondition was not satisfied. It must not proceed to comparison.

---

## 6. Discrepancy Evaluation Scope

### 6.1 What Is Compared

The worker compares price observations across distinct sources for the same product.

Each comparison pair consists of exactly two observations:
- observation A from source X,
- observation B from source Y,
- where X ≠ Y.

### 6.2 Pair Construction Rules

- Pairs must be constructed from observations belonging to the same product context.
- Each pair must involve exactly two distinct source identifiers.
- The pair (A, B) and the pair (B, A) are the same pair. Duplicate pairs must not be
  evaluated twice. The canonical ordering of a pair is determined by sorting source
  identifiers lexicographically — the lesser source identifier is always observation A.
- If more than two observations are present, all eligible distinct-source pairs must
  be evaluated.
- Observations from the same source must not be paired with each other.

### 6.3 Comparison Eligibility Within Worker Scope

At this stage, observations have already been validated and confirmed eligible by
earlier pipeline stages. The worker must still verify:

- both observations in a pair have a normalized price strictly greater than zero,
- both observations have distinct, non-equal source identifiers.

Any pair that fails these checks within this worker must be skipped and logged.
It must not cause the entire evaluation to fail unless no eligible pairs remain.

### 6.4 Multiple Pairs

If the input context contains more than two observations from more than two sources,
the worker evaluates all eligible distinct-source pairs.

If any single pair produces a DISCREPANCY_DETECTED result, the overall worker result
is DISCREPANCY_DETECTED.

If all pairs produce NO_DISCREPANCY results, the overall worker result is
NO_DISCREPANCY.

The worker must include evaluation detail for all pairs in its output, regardless of
the overall result classification.

---

## 7. Comparison Rules

All comparison rules are derived from the spec directives in Section 2.
The worker must not invent, modify, or approximate these rules.

### 7.1 Absolute Difference

For each pair (observation A, observation B):

```
absolute_difference = |normalized_price_A - normalized_price_B|
```

This value must be computed for every eligible pair regardless of the configured
threshold method.

### 7.2 Percentage Difference

For each pair (observation A, observation B):

```
percentage_difference = (|normalized_price_A - normalized_price_B| / min(normalized_price_A, normalized_price_B)) * 100
```

The denominator is the lesser of the two prices.
This value must be computed for every eligible pair regardless of the configured
threshold method.

### 7.3 Threshold Evaluation

A discrepancy exists for a pair if the computed difference crosses the configured
threshold. The threshold method is loaded from the discrepancy rule set.

**ABSOLUTE method:**
A discrepancy exists if `absolute_difference >= absolute_threshold`.

**PERCENTAGE method:**
A discrepancy exists if `percentage_difference >= percentage_threshold`.

**BOTH method:**
A discrepancy exists if `absolute_difference >= absolute_threshold`
AND `percentage_difference >= percentage_threshold`.
Both conditions must be met simultaneously.

### 7.4 Directionality

For each pair where a discrepancy is detected, the worker must record directionality:
- `lower_price_source`: the source identifier with the lower normalized price.
- `higher_price_source`: the source identifier with the higher normalized price.

If both prices are equal, no discrepancy exists (difference is zero and cannot meet
any threshold greater than zero). This pair must produce NO_DISCREPANCY.

### 7.5 Noise Filtering

A pair must be excluded from discrepancy detection (treated as NO_DISCREPANCY) when
any of the following apply. These filters are defined in the spec and must not be
modified here:

1. The absolute difference is zero (prices are equal).
2. The absolute difference is below the absolute threshold when using ABSOLUTE or
   BOTH method.
3. The percentage difference is below the percentage threshold when using PERCENTAGE
   or BOTH method.
4. Either observation has a normalized price of zero or less.
5. Both observations share the same source identifier.
6. The observations reference unrelated product contexts (must not occur after Stage 2,
   but must be defended against).
7. A currency mismatch exists between the two observations and no normalization has
   been applied. Currency normalization is a Stage 2 responsibility. If the worker
   detects mismatched currencies at this stage, it must treat the pair as ineligible
   and log the skip.

Each skipped pair must be logged with the reason for exclusion.

---

## 8. Discrepancy Output Structure

The worker must return exactly one structured output object for every execution.

The output must classify the overall result as one of three states:
DISCREPANCY_DETECTED, NO_DISCREPANCY, or PROCESSING_FAILURE.

### 8.1 DISCREPANCY_DETECTED Output

Returned when at least one eligible pair crosses the configured threshold.

Required top-level fields:

| Field | Type | Description |
|---|---|---|
| `result` | string | `"DISCREPANCY_DETECTED"` |
| `product_id` | string | Product identifier from the input context. |
| `pipeline_execution_id` | string | Links this result to the parent pipeline run. |
| `evaluation_reference_timestamp` | datetime | The reference time used for this evaluation. |
| `rule_id` | string | Identifier of the discrepancy rule set applied. |
| `threshold_method` | string | The method used: `ABSOLUTE`, `PERCENTAGE`, or `BOTH`. |
| `pairs_evaluated` | integer | Total number of distinct-source pairs evaluated. |
| `pairs_with_discrepancy` | integer | Number of pairs that crossed the threshold. |
| `pair_results` | list | Full evaluation detail for every pair (see below). |

Required fields per pair result entry:

| Field | Type | Description |
|---|---|---|
| `pair_id` | string | Stable canonical identifier for this pair (derived from sorted source identifiers). |
| `source_a` | string | Source identifier of observation A (lesser by lexicographic sort). |
| `source_b` | string | Source identifier of observation B. |
| `observation_id_a` | string | Observation identifier for source A. |
| `observation_id_b` | string | Observation identifier for source B. |
| `price_a` | numeric | Normalized price for source A. |
| `price_b` | numeric | Normalized price for source B. |
| `absolute_difference` | numeric | Computed absolute difference. |
| `percentage_difference` | numeric | Computed percentage difference. |
| `absolute_threshold_used` | numeric | The configured absolute threshold value (if applicable). |
| `percentage_threshold_used` | numeric | The configured percentage threshold value (if applicable). |
| `lower_price_source` | string | Source with the lower price. |
| `higher_price_source` | string | Source with the higher price. |
| `pair_result` | string | `"DISCREPANCY_DETECTED"` or `"NO_DISCREPANCY"` for this specific pair. |
| `threshold_met` | boolean | Whether this pair crossed the threshold. |

### 8.2 NO_DISCREPANCY Output

Returned when all eligible pairs were evaluated and none crossed the configured
threshold, or when all pairs were excluded by noise filters.

Required fields:

| Field | Type | Description |
|---|---|---|
| `result` | string | `"NO_DISCREPANCY"` |
| `product_id` | string | Product identifier from the input context. |
| `pipeline_execution_id` | string | Links this result to the parent pipeline run. |
| `evaluation_reference_timestamp` | datetime | The reference time used for this evaluation. |
| `rule_id` | string | Identifier of the discrepancy rule set applied. |
| `threshold_method` | string | The method used: `ABSOLUTE`, `PERCENTAGE`, or `BOTH`. |
| `pairs_evaluated` | integer | Total number of distinct-source pairs evaluated. |
| `pairs_skipped` | integer | Number of pairs excluded by noise filters, with reasons. |
| `pair_results` | list | Full evaluation detail for every pair, including skipped pairs. |

### 8.3 PROCESSING_FAILURE Output

Returned when the worker encounters an unexpected error or a failed precondition
check within this stage.

Required fields:

| Field | Type | Description |
|---|---|---|
| `result` | string | `"PROCESSING_FAILURE"` |
| `product_id` | string | Product identifier if available; otherwise null. |
| `pipeline_execution_id` | string | Links this result to the parent pipeline run. |
| `evaluation_reference_timestamp` | datetime | The reference time if available; otherwise null. |
| `failure_stage` | string | `"DISCREPANCY_WORKER"` |
| `failure_reason` | string | Description of what failed and why. |
| `retriable` | boolean | Whether this failure may be retried after correction. |

---

## 9. Failure Modes

### 9.1 Missing or Invalid Normalized Context
- Cause: the normalized input context is absent, incomplete, or contains a null
  required field when the worker receives it.
- Classification: PROCESSING_FAILURE.
- Behavior: halt immediately, surface the failure with the missing or invalid field
  identified.
- Retriable: no — this indicates a pipeline defect in Stage 2 or Stage 3 that must
  be corrected before rerunning.

### 9.2 Empty or Null Discrepancy Rule Set
- Cause: the rule set is absent, empty, or contains no usable threshold definition.
- Classification: PROCESSING_FAILURE.
- Behavior: halt immediately, surface the failure.
- Retriable: no — the rule set must be configured before retrying.

### 9.3 No Eligible Pairs After Noise Filtering
- Cause: all observation pairs were excluded by noise filtering rules (e.g., all pairs
  share a source, or all prices are equal).
- Classification: NO_DISCREPANCY (not a failure — a valid evaluation outcome).
- Behavior: return a complete NO_DISCREPANCY result with the reason each pair was
  excluded.
- Retriable: not applicable.

### 9.4 Division by Zero in Percentage Calculation
- Cause: both observations in a pair have a normalized price of zero.
- Classification: this pair is excluded by noise filter rule 4 (price ≤ 0) and must
  not reach the percentage calculation. If reached despite this guard, the worker
  must skip the pair and log a PROCESSING_FAILURE for that pair only.
- Behavior: log the anomaly, skip the pair, continue evaluating other pairs.
- Retriable: not applicable at the pair level.

### 9.5 Unexpected Runtime Error
- Cause: an unhandled exception occurs during evaluation.
- Classification: PROCESSING_FAILURE.
- Behavior: surface the exception explicitly with the pair or stage context in which
  it occurred.
- Retriable: depends on the nature of the error; default to `retriable: false` unless
  clearly transient.

---

## 10. Determinism Rules

The worker must behave deterministically in all circumstances.

1. The same normalized input context and the same rule set must always produce the
   same result classification.
2. The same input must always produce the same set of pair results, in the same order.
3. Pair ordering within `pair_results` must be stable and derived from a fixed sort
   criterion — canonical pair ordering is by lexicographic sort of source identifiers.
4. Computed values (`absolute_difference`, `percentage_difference`) must be calculated
   using consistent precision rules defined in the spec. No floating-point rounding
   behavior may differ between runs.
5. The `evaluation_reference_timestamp` must be passed in explicitly from the pipeline
   execution context. The worker must not call the system clock.
6. No randomness of any kind may affect evaluation results.
7. Threshold comparison must use consistent boundary semantics: a difference exactly
   equal to the threshold meets the threshold (i.e., `>=` not `>`).
8. Noise filtering rules must be applied in a fixed, documented order on every run.
   The order of filter application must not vary.

---

## 11. Idempotency Considerations

The Discrepancy Worker does not write to any persistent system.

Because it has no side effects, running it multiple times on the same normalized
context and rule set is inherently safe and produces the same result.

However, the following rules apply to its use within the pipeline:

1. The pipeline must not run the worker more than once per pipeline execution instance
   unless the prior attempt resulted in a PROCESSING_FAILURE.
2. If the pipeline resumes after a PROCESSING_FAILURE in this stage, the worker must
   be re-executed from scratch using the same normalized context. The prior failed
   result must not be partially reused.
3. The worker's output must not be cached across pipeline execution instances. Rule
   set configuration may change between executions.
4. The `pipeline_execution_id` in the output provides the link for deduplication at
   the persistence layer — this worker is not responsible for deduplication, but its
   output must carry the information needed for Stage 7 to enforce it.

---

## 12. Logging Requirements

The worker must emit structured log entries at the following points:

- **Worker start**: product identifier, pipeline execution identifier, number of
  observations received, reference timestamp.
- **Pair construction**: number of distinct-source pairs identified.
- **Per pair evaluation**: pair identifier, source identifiers, computed differences,
  threshold values, and pair-level result classification.
- **Per pair skip**: pair identifier, source identifiers, and the noise filter rule
  that caused the exclusion.
- **Worker end**: overall result classification, total pairs evaluated, pairs with
  discrepancy, pairs skipped, reference timestamp.
- **PROCESSING_FAILURE**: failure reason, context available at time of failure,
  whether the failure is retriable.

Log entries must be structured and machine-readable.
Log entries must not include secrets, credentials, or tokens.
Log entries must not include raw external API payloads.
Prices and source identifiers may be logged as they are not sensitive operational
data, but must not appear alongside credentials or session tokens.

---

## 13. What This Worker Must NOT Do

The following are explicitly forbidden:

- **Score opportunities.** The worker determines whether a discrepancy exists. It does
  not assign a score to it. Scoring is the responsibility of Stage 5.
- **Trigger alerts.** The worker produces a discrepancy result. It does not evaluate
  alert eligibility, send notifications, or interact with any alerting system.
  Alert eligibility is the responsibility of Stage 6.
- **Fetch data.** The worker operates entirely on the normalized context it receives.
  It must not query the database, call an external API, or retrieve any data from
  outside the input.
- **Modify input.** The worker must not alter any field in the normalized context.
  It reads and evaluates — it does not write back.
- **Normalize data.** Price normalization, source canonicalization, and currency
  conversion are the responsibility of Stage 2. If the worker encounters data that
  appears to need normalization, it must treat it as a PROCESSING_FAILURE, not
  attempt to normalize it.
- **Infer missing data.** If a required field is absent from the normalized context,
  the worker must surface a PROCESSING_FAILURE. It must not substitute defaults or
  derive values.
- **Apply rules not in the spec.** The threshold logic, noise filters, and comparison
  formulas must come from the configured rule set and the spec directives. The worker
  must not invent, estimate, or approximate them.
- **Call an AI model.** No AI model may be invoked at runtime to determine whether a
  discrepancy exists or how to evaluate a pair.
- **Persist results.** Writing the discrepancy result to the system of record is the
  responsibility of Stage 7. The worker returns a structured result object — it does
  not write it.
- **Produce partial results.** If a PROCESSING_FAILURE occurs, the worker must not
  return a partial DISCREPANCY_DETECTED or NO_DISCREPANCY result alongside it.
- **Silently skip a pair without logging.** Every excluded pair must be logged with
  the reason for exclusion.
- **Produce non-deterministic output.** Any behavior that produces different results
  on identical inputs is a defect.

---

## 14. Success Criteria

The worker is successful when:

1. Two valid observations from distinct sources with an absolute difference above the
   configured absolute threshold produce a DISCREPANCY_DETECTED result with the
   correct pair detail.
2. Two valid observations from distinct sources with a difference below the configured
   threshold produce a NO_DISCREPANCY result with pair-level evaluation detail.
3. A pair of observations from the same source is excluded by noise filter rule 5 and
   the skip is logged with the correct reason.
4. A pair where both observations have equal prices is excluded and the result is
   NO_DISCREPANCY.
5. Three observations from three distinct sources produce three evaluated pairs, with
   each pair independently classified.
6. When BOTH threshold method is configured, a pair that exceeds the absolute threshold
   but not the percentage threshold produces NO_DISCREPANCY for that pair.
7. Running the worker twice on the same normalized context and rule set produces
   identical output both times.
8. A null or empty rule set causes a PROCESSING_FAILURE with `retriable: false`.
9. A normalized context missing a required observation field causes a PROCESSING_FAILURE
   identifying the missing field.
10. All pair results are ordered by the canonical lexicographic source sort on every run.
11. Computed `absolute_difference` and `percentage_difference` values are correct for
    all test cases to the precision defined in the spec.
12. The `evaluation_reference_timestamp` in the output exactly matches the value passed
    in — the system clock is never used.
13. All three result classifications are covered by unit tests with deterministic inputs.
14. No data fetch, write, or external call occurs during any test execution.

---

## 15. Non-Acceptance Conditions

The worker is not acceptable if any of the following are true:

- A pair with a difference below the configured threshold is classified as
  DISCREPANCY_DETECTED.
- A pair with a difference above the configured threshold is classified as
  NO_DISCREPANCY without a documented noise filter reason.
- A pair involving two observations from the same source is evaluated instead of
  excluded.
- The pair (A, B) and the pair (B, A) are both evaluated as separate pairs for the
  same two observations.
- The worker calls the system clock to determine the evaluation timestamp.
- The worker calls a database, external API, or any system outside the input context.
- The worker modifies any field in the normalized input context.
- Percentage difference is computed using the larger price as the denominator instead
  of the smaller.
- A PROCESSING_FAILURE is returned without identifying what failed and whether it is
  retriable.
- Any pair is skipped without a log entry identifying the reason.
- Running the worker twice on identical input produces different pair orderings or
  different computed values.
- An AI model is invoked to make any evaluation decision.
- Opportunity scoring logic or alert eligibility logic appears in this worker.
- A discrepancy result is written to the system of record by this worker.
- Unit tests do not cover all three result classifications.
- Any noise filter rule is missing, inverted, or applied in a non-deterministic order.

Any of these conditions is a blocking defect. The worker must not be considered
complete while any non-acceptance condition is present.
