# Scoring Worker Contract

## 1. Purpose

This document is the authoritative contract for the Scoring Worker — Stage 5 of the AACE
Opportunity Pipeline.

It defines:

- what this worker does and why it exists,
- what inputs it requires and what preconditions must be satisfied before it runs,
- the exact scope of scoring evaluation it must perform,
- the rules it must apply to compute a deterministic score,
- what outputs it must produce,
- how it must behave under failure,
- what it must never do.

This is not an implementation document.
It does not contain code, pseudocode, or framework-specific instructions.
It defines the behavioral contract that implementation must satisfy.

---

## 2. Relationship to Spec Repo

This worker implements behavior defined in the following AACE spec directives:

- `directives/spec/features/opportunity_scoring/00_overview.md` — feature objective, determinism requirement, explainability requirement
- `directives/spec/features/opportunity_scoring/01_requirements.md` — input requirements, core scoring factors, scoring model, ranking requirements, failure handling
- `directives/spec/features/opportunity_scoring/02_acceptance_criteria.md` — scoring eligibility, score calculation, output structure, traceability, determinism, non-acceptance conditions
- `directives/spec/features/opportunity_scoring/03_scoring_rules.md` — base scoring model, required and optional factors, weighting rules, normalization rules, tie-breaking rules, noise protection
- `directives/spec/06_architecture.md` — three-layer model, pipeline data flow, domain responsibilities
- `directives/spec/12_autonomous_execution_constraints.md` — execution boundary rules
- `directives/spec/features/price_monitoring/03_discrepancy_rules.md` — discrepancy result structure consumed by this worker

This worker must never redefine the scoring factors, weights, formulas, or thresholds those
directives establish.
If a scoring rule is missing, ambiguous, or in conflict, implementation must stop and the spec
must be updated first.

Business rules flow one direction: spec → this worker.

---

## 3. Worker Objective

The Scoring Worker is the stage that converts a confirmed price discrepancy into a prioritized,
explainable opportunity score.

Its objective is to consume a valid DISCREPANCY_DETECTED result and produce a single deterministic
score that reflects the relative value of that discrepancy according to the spec-defined scoring
rules.

The worker must:

- confirm that the incoming discrepancy result satisfies scoring eligibility preconditions,
- apply only the scoring factors and weights defined in the spec,
- compute a single numeric score using the spec-defined formula,
- preserve each factor value and its individual contribution to the final score,
- produce ranking-ready output that downstream stages can use without further computation,
- produce an explanation-ready breakdown so that any scorer can reconstruct how the score was derived.

The worker must not:

- detect discrepancies,
- trigger or evaluate alert eligibility,
- persist data to any system of record,
- fetch or enrich data from external sources,
- define, invent, or adjust scoring weights outside those provided in the configured rule set.

---

## 4. Required Inputs

The worker requires a single structured input containing the following:

**Discrepancy Result (from Stage 4)**

- `pipeline_execution_id` — the unique identifier for this pipeline run, carried forward from Stage 1.
- `pair_id` — the canonical pair identifier for the source pair that produced the discrepancy.
- `discrepancy_result` — must be `DISCREPANCY_DETECTED`; any other value is a precondition failure.
- `source_a` — canonical identifier of the first source in the pair.
- `source_b` — canonical identifier of the second source in the pair.
- `price_a` — normalized price from source_a.
- `price_b` — normalized price from source_b.
- `absolute_difference` — precomputed `|price_a - price_b|` from the discrepancy worker.
- `percentage_difference` — precomputed percentage difference from the discrepancy worker.
- `threshold_method` — the threshold method applied (`ABSOLUTE`, `PERCENTAGE`, or `BOTH`).
- `lower_price_source` — canonical identifier of the source with the lower price.
- `higher_price_source` — canonical identifier of the source with the higher price.
- `observation_timestamp_a` — ISO 8601 timestamp of the observation from source_a.
- `observation_timestamp_b` — ISO 8601 timestamp of the observation from source_b.
- `product_id` — stable product identifier linking to the system of record.

**Scoring Configuration (from spec-defined rule set)**

- `scoring_factors` — the ordered list of factor definitions to apply, each including:
  - `factor_name` — unique name for this factor (e.g., `price_difference`, `freshness`).
  - `factor_type` — which computation method to use (e.g., `absolute_difference`, `percentage_difference`, `freshness_decay`).
  - `weight` — the numeric weight assigned to this factor in the scoring formula.
- `score_range` — the defined minimum and maximum for the output score (e.g., `0` to `100`).
- `normalization_method` — the method used to scale raw factor values to the score range, if normalization is applied.
- `tie_break_order` — the ordered list of tie-break criteria to apply when scores are equal.

**Reference Timestamp**

- `freshness_reference_timestamp` — an explicit ISO 8601 timestamp passed into this worker
  representing the reference point for freshness calculations.
  This timestamp must never be derived from the system clock within the worker.

No input field may be inferred, defaulted silently, or invented by this worker.
If a required field is absent, the worker must reject the input with a structured
`PROCESSING_FAILURE` identifying the missing field.

---

## 5. Preconditions

The following preconditions must be satisfied before this worker begins scoring.
If any precondition is not met, the worker must halt immediately with a structured failure result.
It must not attempt to score.

1. The incoming `discrepancy_result` is `DISCREPANCY_DETECTED`. Any other value (including `NO_DISCREPANCY` or `PROCESSING_FAILURE`) is a precondition violation.
2. The `scoring_factors` list is non-empty and has been loaded from the spec-defined configuration. An empty or unloaded factor list is a precondition violation.
3. Each factor in `scoring_factors` has an explicit, non-null weight.
4. The `score_range` defines valid minimum and maximum bounds, where minimum < maximum.
5. All price values (`price_a`, `price_b`) are positive, finite numbers. Zero or negative prices are a precondition violation.
6. Both `observation_timestamp_a` and `observation_timestamp_b` are valid ISO 8601 timestamps.
7. The `freshness_reference_timestamp` is present, valid, and not earlier than either observation timestamp.
8. The `pipeline_execution_id` is present and non-empty.

A precondition failure is not a scoring error.
It is a structural rejection indicating this worker should not have been invoked in this state.
It must be returned as a structured `PROCESSING_FAILURE` with failure reason `PRECONDITION_VIOLATION`.

---

## 6. Scoring Evaluation Scope

This worker evaluates exactly one discrepancy result per invocation.
It does not batch, aggregate, or compare across multiple discrepancies.

The worker evaluates:

- the detected price discrepancy represented by the incoming `DISCREPANCY_DETECTED` result,
- using only the scoring factors defined in the loaded `scoring_factors` configuration,
- against the `score_range` and `normalization_method` defined in the configuration.

The worker does not evaluate:

- whether the discrepancy was correctly detected (that is Stage 4's responsibility),
- whether the score qualifies for an alert (that is Stage 6's responsibility),
- whether a prior score exists for this discrepancy (idempotency is handled by the pipeline coordinator, not this worker),
- whether the source data is fresh (freshness is evaluated using the explicit `freshness_reference_timestamp` passed in; the worker does not determine reference time).

---

## 7. Scoring Rules

This section describes the scoring rules this worker must apply.
These rules are derived from `directives/spec/features/opportunity_scoring/03_scoring_rules.md`.

### 7.1 Primary Factor — Price Difference

The primary scoring factor is the price difference between the two observed prices.

The worker must compute one or both of the following, as specified by the loaded `scoring_factors` configuration:

**Absolute Difference**

```
absolute_difference = |price_a - price_b|
```

The absolute difference is already present in the incoming discrepancy result.
The worker must use the value as computed by the discrepancy worker — it must not recompute it.

**Percentage Difference**

```
percentage_difference = (|price_a - price_b| / min(price_a, price_b)) * 100
```

The percentage difference is already present in the incoming discrepancy result.
The worker must use the value as computed by the discrepancy worker — it must not recompute it.

A higher price difference value must produce a higher factor contribution, all else equal.

### 7.2 Optional Factor — Freshness

If `freshness` is listed in the `scoring_factors` configuration, the worker must compute a
freshness factor based on the age of the most recent observation relative to the
`freshness_reference_timestamp`.

Freshness computation:

```
most_recent_observation_timestamp = max(observation_timestamp_a, observation_timestamp_b)
observation_age_seconds = (freshness_reference_timestamp - most_recent_observation_timestamp).total_seconds()
```

A more recent observation (smaller `observation_age_seconds`) must produce a higher freshness
factor value, all else equal.

If `freshness` is not listed in `scoring_factors`, this factor must not be computed or applied.

### 7.3 Scoring Formula

The final score must be computed using the following general form:

```
raw_score = sum(weight_i * normalized_factor_value_i)  for each factor_i in scoring_factors
```

Where:

- `weight_i` is the weight defined for factor `i` in the loaded configuration.
- `normalized_factor_value_i` is the factor's raw value scaled to the defined `score_range` using the configured `normalization_method`.

The sum of all weights defined in `scoring_factors` must equal 1.0 (or an equivalent
proportional total if the configuration uses integer weights). If weights do not sum to a
valid total, the worker must raise a `PROCESSING_FAILURE` with failure reason
`INVALID_SCORING_CONFIGURATION`.

The resulting `raw_score` must be bounded to the defined `score_range`.
If the computed value falls outside the range due to floating-point edge cases, it must be
clamped to the nearest boundary and this clamping must be noted in the output.

### 7.4 Normalization

If `normalization_method` is defined in the configuration, factor values must be normalized
before being weighted and summed.

Normalization must be:

- deterministic: the same factor value always normalizes to the same result.
- documented: the normalization method must be recorded in the scoring output.
- bounded: normalized values must fall within the defined `score_range`.

If no `normalization_method` is configured, factor values are used as-is.
The worker must not invent a normalization method at runtime.

### 7.5 Tie-Breaking

If two discrepancies produce the same score (relevant when this worker's output is later used
for ranking), the output must include the full per-factor breakdown needed to apply tie-breaking
deterministically.

The worker itself does not rank; it produces the structured output required for ranking.
The tie-break order defined in `tie_break_order` is recorded in the output and applied by
downstream consumers. The worker must preserve this configuration reference in its output.

Defined fallback tie-break priority (from spec):

1. Higher absolute difference.
2. More recent observation (lower `observation_age_seconds`).
3. Lower `product_id` (stable lexicographic fallback).

This tie-break order applies only when `tie_break_order` is not explicitly overridden in the
loaded configuration.

---

## 8. Scoring Output Structure

### 8.1 SCORED_OPPORTUNITY

Produced when all preconditions are satisfied and a score is successfully computed.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `SCORED_OPPORTUNITY`. |
| `pipeline_execution_id` | string | Carried from input without modification. |
| `score_result_id` | string | A deterministic identifier derived from `pipeline_execution_id` and `pair_id`. Must be stable across retries. |
| `product_id` | string | Carried from input without modification. |
| `pair_id` | string | Carried from input without modification. |
| `discrepancy_reference` | object | Echo of the key discrepancy fields: `source_a`, `source_b`, `price_a`, `price_b`, `absolute_difference`, `percentage_difference`, `threshold_method`. |
| `score` | number | The final computed score, bounded within `score_range`. |
| `score_range` | object | The configured `min` and `max` bounding the score. |
| `factors_applied` | list | One entry per scoring factor applied. Each entry includes: `factor_name`, `factor_type`, `raw_value`, `normalized_value`, `weight`, `weighted_contribution`. |
| `weights_sum` | number | The total of all weights applied. Must equal the configured valid total. |
| `normalization_method` | string or null | The normalization method applied, or null if none. |
| `score_clamped` | boolean | True if the raw score was clamped to the score range boundary. False otherwise. |
| `tie_break_order` | list | The configured tie-break criteria, in priority order, for downstream ranking use. |
| `freshness_reference_timestamp` | string | The ISO 8601 reference timestamp passed into this worker, included for auditability. |
| `scoring_timestamp` | string | ISO 8601 timestamp marking when scoring computation completed. Must be passed in, not derived from system clock. |

### 8.2 NO_SCORE

Produced when the incoming discrepancy result is not eligible for scoring under explicit
spec-defined conditions that are not a runtime error.

The only conditions that may produce `NO_SCORE` are those explicitly defined in the spec as
ineligibility conditions.
An absent or misconfigured rule set is not a `NO_SCORE` condition — it is a `PROCESSING_FAILURE`.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `NO_SCORE`. |
| `pipeline_execution_id` | string | Carried from input without modification. |
| `pair_id` | string | Carried from input without modification. |
| `product_id` | string | Carried from input without modification. |
| `ineligibility_reason` | string | The explicit spec-defined condition that disqualified this discrepancy from scoring. |
| `discrepancy_result_received` | string | The `discrepancy_result` value received from Stage 4. |

### 8.3 PROCESSING_FAILURE

Produced when a runtime error, configuration error, or precondition violation prevents scoring
from completing.

| Field | Type | Description |
|---|---|---|
| `result` | string | Always `PROCESSING_FAILURE`. |
| `pipeline_execution_id` | string | Carried from input if present; null if the failure occurred before the input could be parsed. |
| `pair_id` | string | Carried from input if present; null otherwise. |
| `product_id` | string | Carried from input if present; null otherwise. |
| `failure_reason` | string | One of: `PRECONDITION_VIOLATION`, `INVALID_SCORING_CONFIGURATION`, `INVALID_FACTOR_VALUE`, `INVALID_DISCREPANCY_INPUT`, `UNEXPECTED_RUNTIME_ERROR`. |
| `failure_stage` | string | The sub-stage within this worker where the failure occurred (e.g., `PRECONDITION_CHECK`, `FACTOR_COMPUTATION`, `SCORE_ASSEMBLY`). |
| `retriable` | boolean | True if the failure is transient and a retry may succeed; false if the input or configuration must be corrected first. |
| `error_context` | string | A human-readable description of the failure cause, safe to log without exposing secrets or raw credential payloads. |

---

## 9. Failure Modes

### 9.1 Invalid Discrepancy Input

- **Cause**: The incoming discrepancy result is missing required fields, contains malformed values, or presents a `discrepancy_result` other than `DISCREPANCY_DETECTED`.
- **Failure reason**: `INVALID_DISCREPANCY_INPUT`.
- **Retriable**: No — the upstream discrepancy result must be corrected or re-evaluated.
- **Behavior**: Immediate halt, no scoring attempted, structured `PROCESSING_FAILURE` returned.

### 9.2 Missing or Invalid Scoring Configuration

- **Cause**: The `scoring_factors` list is absent, empty, or the loaded configuration contains incomplete factor definitions. Weights do not sum to a valid total. Score range is absent or invalid.
- **Failure reason**: `INVALID_SCORING_CONFIGURATION`.
- **Retriable**: No — the configuration must be corrected before rerunning.
- **Behavior**: Immediate halt, structured `PROCESSING_FAILURE` returned.

### 9.3 Invalid Factor Value

- **Cause**: A factor computation produces a value that cannot be used in the scoring formula — for example, a zero denominator in a normalization step, a non-finite floating-point result, or a factor value outside any reasonable domain boundary.
- **Failure reason**: `INVALID_FACTOR_VALUE`.
- **Retriable**: Depends on cause. If the factor value is deterministically invalid (e.g., zero price in a denominator), this is terminal. If caused by transient data access, it may be retriable.
- **Behavior**: Halt at factor computation stage, structured `PROCESSING_FAILURE` returned.

### 9.4 Unexpected Runtime Error

- **Cause**: An unhandled exception or unexpected internal state that does not fall into the above categories.
- **Failure reason**: `UNEXPECTED_RUNTIME_ERROR`.
- **Retriable**: Yes — treat as potentially transient; retry up to the configured limit.
- **Behavior**: Explicit exception surfaced, structured `PROCESSING_FAILURE` returned with full error context.

---

## 10. Determinism Rules

The following rules govern the deterministic behavior of this worker.
Violating any rule is a non-acceptance condition.

1. **Same input → same score.** Given identical discrepancy input and identical scoring configuration, this worker must produce the same score on every execution, without exception.
2. **No hidden heuristics.** Every value that contributes to the final score must appear in the `factors_applied` output. No adjustment, bonus, penalty, or scalar that is not defined in the loaded `scoring_factors` configuration may affect the result.
3. **No runtime AI decisions.** No AI model may be called within this worker to determine factor values, weights, scores, eligibility decisions, or any other aspect of the scoring output. All logic is deterministic and code-defined.
4. **No system-clock-derived freshness.** Freshness calculations must use the `freshness_reference_timestamp` passed explicitly into the worker. The system clock must never be read inside this worker for any scoring purpose.
5. **No random tie behavior.** If tie-breaking is applied downstream, this worker must produce the fields required for deterministic tie resolution. It must not introduce randomness in any field that affects ordering.
6. **No dynamic weight adjustment.** Weights must be loaded from configuration and must not be modified at runtime based on input values, external state, or runtime observations.
7. **No implicit normalization.** If normalization is applied, the normalization method must be loaded from configuration. This worker must not invent or infer a normalization method.
8. **No factor invention.** This worker may only apply factors present in the loaded `scoring_factors` configuration. It must not compute, apply, or record factors that are not explicitly listed.
9. **No coercion of invalid inputs.** If a required input value is missing, null, or out of domain, the worker must fail — not substitute a default or approximation.
10. **Scoring timestamp must be passed in.** The `scoring_timestamp` in the output must be provided as an explicit input to this worker, not derived from the system clock.

---

## 11. Idempotency Considerations

This worker does not persist data.
It is a pure computation stage.

However, the following idempotency rules apply to preserve pipeline-level idempotency:

1. Running this worker multiple times on the same input must produce the same `SCORED_OPPORTUNITY` output, including the same `score_result_id`.
2. The `score_result_id` must be derived deterministically from `pipeline_execution_id` and `pair_id`. It must not be generated randomly.
3. This worker does not check for existing score records. The pipeline coordinator (Stage 7 / idempotency guard) is responsible for detecting and handling duplicate score outputs.
4. If this worker is retried after a `PROCESSING_FAILURE`, it must re-execute from the beginning of its evaluation using the same inputs. It must not resume from a partial intermediate state.

---

## 12. Logging Requirements

This worker must emit a structured log entry at each of the following points:

- **Worker start**: `pipeline_execution_id`, `pair_id`, `product_id`, number of scoring factors loaded, score range.
- **Precondition check completion**: pass or fail, and if fail, which precondition was violated.
- **Factor computation for each factor**: `factor_name`, `raw_value`, `normalized_value`, `weighted_contribution`.
- **Score assembly**: `raw_score`, whether clamping was applied, `final_score`.
- **Worker end**: `result`, `score` (if `SCORED_OPPORTUNITY`), total computation time.
- **Any failure**: `failure_reason`, `failure_stage`, `retriable` status, `error_context`.

Logs must be structured and machine-readable.
Logs must never include secrets, credentials, tokens, or raw API response payloads.
Logs must never include raw price data for external products beyond what is necessary for the
specific computation being logged.

---

## 13. What This Worker Must NOT Do

The following are explicitly forbidden in this worker:

- **Detect discrepancies.** Discrepancy detection is Stage 4's responsibility. This worker consumes a completed `DISCREPANCY_DETECTED` result; it does not re-evaluate whether a discrepancy exists.
- **Trigger or evaluate alert eligibility.** Alert eligibility is Stage 6's responsibility.
- **Persist data.** This worker produces a structured in-memory result only. Writing to any system of record is outside this worker's scope.
- **Fetch or enrich data from external sources.** All data needed for scoring must be present in the inputs passed to this worker. No external API calls, database reads, or network requests may be made.
- **Redefine scoring weights or factors.** Scoring weights, factor definitions, score range, and normalization method are owned by the spec. They must be loaded from configuration — never hardcoded or adjusted within this worker.
- **Apply factors not present in the loaded configuration.** If a factor is not listed in `scoring_factors`, it must not affect the score.
- **Call an AI model at runtime.** No large language model, ML model, or probabilistic system may be invoked to determine, adjust, or explain the score.
- **Use the system clock for freshness or timing.** All time-sensitive computations must use the `freshness_reference_timestamp` provided as explicit input.
- **Produce a partial or ambiguous score.** If this worker cannot produce a complete `SCORED_OPPORTUNITY` result, it must produce a `PROCESSING_FAILURE`. A partial score must never be returned as a valid output.
- **Swallow exceptions silently.** Every failure must surface as a structured `PROCESSING_FAILURE` result with a classified `failure_reason`.
- **Operate on more than one discrepancy per invocation.** This worker scores exactly one discrepancy result per call.
- **Coerce or default missing inputs.** Missing required fields must produce a `PROCESSING_FAILURE`, not a substituted default.

---

## 14. Success Criteria

This worker is successful when:

1. A valid `DISCREPANCY_DETECTED` input with complete scoring configuration produces a `SCORED_OPPORTUNITY` result containing the score, all factor contributions, weights, and normalization method applied.
2. Two identical valid inputs always produce the same `SCORED_OPPORTUNITY` result with the same `score` and the same `score_result_id`.
3. A higher-value discrepancy (larger price difference, under the same scoring configuration) produces a higher score than a lower-value discrepancy.
4. If freshness is a configured factor, a more recent observation produces a higher freshness factor contribution than an older one, all else equal.
5. An input with `discrepancy_result` other than `DISCREPANCY_DETECTED` produces a `PROCESSING_FAILURE` with reason `PRECONDITION_VIOLATION` and no score is computed.
6. An input with a missing or empty `scoring_factors` configuration produces a `PROCESSING_FAILURE` with reason `INVALID_SCORING_CONFIGURATION`.
7. An input where weights do not sum to a valid total produces a `PROCESSING_FAILURE` with reason `INVALID_SCORING_CONFIGURATION`.
8. An input with an invalid factor value (e.g., zero price causing a denominator issue) produces a `PROCESSING_FAILURE` with reason `INVALID_FACTOR_VALUE`.
9. All three result types — `SCORED_OPPORTUNITY`, `NO_SCORE`, `PROCESSING_FAILURE` — are covered by unit tests with deterministic inputs.
10. The `score_result_id` remains stable across retries on the same input.
11. The `factors_applied` list in every `SCORED_OPPORTUNITY` result accounts for every weight contribution such that the sum of `weighted_contribution` values equals the final `score` (within floating-point precision).
12. No secret, credential, or token appears in any log output or committed configuration file.
13. The worker runs fully in a local development environment without production credentials or infrastructure.
14. A reviewer unfamiliar with this codebase can reconstruct how any score was derived using only the `factors_applied` breakdown, the weights, and the scoring formula defined in the spec.

---

## 15. Non-Acceptance Conditions

This worker is not acceptable if any of the following are true:

- An identical input produces different scores across runs.
- A scoring factor or weight is hardcoded within this worker rather than loaded from the configured rule set.
- Any AI model is called at runtime to influence the score, factor values, or eligibility determination.
- A `PROCESSING_FAILURE` does not include both `failure_reason` and `failure_stage`.
- A `SCORED_OPPORTUNITY` result is produced from a discrepancy result that is not `DISCREPANCY_DETECTED`.
- The `factors_applied` list omits any factor that contributed to the final score.
- The `score_result_id` is generated randomly rather than derived deterministically from `pipeline_execution_id` and `pair_id`.
- Freshness is calculated using the system clock rather than the explicit `freshness_reference_timestamp`.
- A missing or invalid required input is silently defaulted rather than surfaced as a failure.
- The weight sum validation is skipped, allowing a misconfigured factor set to produce a score.
- An exception is swallowed and a partial or guessed score is returned.
- Unit tests do not cover all three result classifications (`SCORED_OPPORTUNITY`, `NO_SCORE`, `PROCESSING_FAILURE`).
- Any committed file contains a secret, token, API key, or credential.
- The `SCORED_OPPORTUNITY` output cannot be traced back to the discrepancy that produced it without external context.
