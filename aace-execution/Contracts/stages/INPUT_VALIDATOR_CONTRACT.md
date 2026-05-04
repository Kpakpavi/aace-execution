# Input Validator Contract

## 1. Purpose

This document is the authoritative contract for the AACE Input Validator.

It defines:

- what the validator is responsible for,
- what input domains it covers,
- the exact validation rules it must enforce,
- what it must produce as output,
- how it must classify failures,
- what it must never do.

The Input Validator is the first stage of the Opportunity Pipeline Job (defined in
`OPPORTUNITY_PIPELINE_JOB.md`). No pipeline stage may begin until the validator has
produced a confirmed VALID result.

This is not an implementation document. It contains no code, pseudocode, or
framework-specific instructions. It defines the behavioral contract that
implementation must satisfy.

---

## 2. Relationship to Spec Repo

This validator enforces rules defined in the following AACE spec directives:

- `directives/spec/features/product_ingestion/03_input_validation.md` — field-level
  validation rules for products, listings, and prices
- `directives/spec/features/product_ingestion/01_requirements.md` — ingestion
  validation requirements and forbidden behaviors
- `directives/spec/features/price_monitoring/01_requirements.md` — required input
  conditions for price monitoring eligibility
- `directives/spec/features/price_monitoring/03_discrepancy_rules.md` — freshness
  rules, source policies, noise filtering preconditions
- `directives/spec/features/opportunity_scoring/01_requirements.md` — preconditions
  for scoring input validity
- `directives/spec/12_autonomous_execution_constraints.md` — determinism,
  idempotency, and execution boundary rules

This validator must never redefine the rules those documents establish.
If a validation rule is missing, ambiguous, or in conflict with another directive,
implementation must stop and the spec must be updated first.

Rule ownership flows one direction: spec → this validator.

---

## 3. Validator Objective

The Input Validator has one objective:

**Determine with certainty whether a given input is safe to process.**

It answers exactly one question: is this input valid, invalid, or does it fail a
structural precondition?

To do this it must:

- check that all required fields are present,
- check that all fields are the correct type,
- check that all values are within allowed ranges,
- check that relationships between entities are structurally coherent,
- check that observation timestamps meet freshness requirements,
- check that source identifiers belong to the allowed source set,
- classify the result clearly as VALID, INVALID, or PRECONDITION_FAILURE,
- return a structured output that the pipeline can act on without ambiguity.

The validator must not do anything else.
It does not transform, enrich, infer, normalize, or persist.
It validates and classifies — nothing more.

---

## 4. Validation Scope

The validator covers all inputs required by the Opportunity Pipeline Job.

### 4.1 Product Input

The validator must check all product-level fields provided in the pipeline input context.

### 4.2 Listing Input

The validator must check all listing-level fields for each listing in the input context.

### 4.3 Price Observation Input

The validator must check all price observation records associated with listings in the
input context.

### 4.4 Source Identifiers

The validator must check that every source identifier present in the input is
recognized, non-empty, and belongs to the allowed source set as defined in the spec.

### 4.5 Timestamps

The validator must check that every observation timestamp is well-formed and falls
within the freshness window defined in the spec.

### 4.6 Structural Relationships

The validator must check that the structural relationships between entities are intact:
product ↔ listings, listings ↔ observations, observations ↔ sources.

### 4.7 Comparison Eligibility Preconditions

The validator must check that the minimum structural conditions for discrepancy
detection are present: at least two observations from distinct, valid sources for
the same product.

---

## 5. Required Inputs

The validator receives a single structured input context.

The following fields are required. Their absence or failure constitutes a validation
failure unless otherwise specified.

### 5.1 Product Fields

| Field | Type | Rule |
|---|---|---|
| product_id | string | Required. Non-empty. No invalid characters. |
| product_name OR external_id | string | At least one must be present and non-empty. |

### 5.2 Listing Fields (per listing)

| Field | Type | Rule |
|---|---|---|
| listing_id | string | Required. Non-empty. Unique within source. |
| source | string | Required. Non-empty. Must belong to allowed source set. |
| external_id | string | Required. Non-empty. Must uniquely identify listing within source. |
| price | numeric | Required. Must be numeric. Must be > 0. Must not be null or negative. |
| product_ref | string | Required. Must reference the product_id in this input context. |

### 5.3 Price Observation Fields (per observation)

| Field | Type | Rule |
|---|---|---|
| observation_id | string | Required. Non-empty. |
| listing_ref | string | Required. Must reference a listing_id in this input context. |
| source | string | Required. Non-empty. Must match the source of the referenced listing. |
| observed_price | numeric | Required. Must be numeric. Must be > 0. Must not be null or negative. |
| observed_at | datetime | Required. Must be a valid datetime. Must be within freshness window. |

### 5.4 Rule Set Fields

| Field | Type | Rule |
|---|---|---|
| discrepancy_rule_set | object/config | Required. Must be non-null and non-empty. |
| scoring_factor_set | object/config | Required. Must be non-null and non-empty. |
| alert_threshold | numeric | Required. Must be numeric and > 0. |

### 5.5 Structural Relationship Requirements

- Every listing must reference a product_id that exists in the input context.
- Every observation must reference a listing_id that exists in the input context.
- Every observation's source must match the source of its referenced listing.
- No orphan listing (a listing with no product reference) may be present.
- No orphan observation (an observation with no listing reference) may be present.

### 5.6 Comparison Eligibility Requirement

- The input must contain at least two price observations from at least two distinct,
  valid sources for the same product.
- If this condition is not met, the result is PRECONDITION_FAILURE, not
  VALIDATION_FAILURE (the input may be structurally correct but insufficient for
  pipeline execution).

---

## 6. Validation Categories

The validator applies checks in the following categories in order. A failure in any
category terminates validation with a classified result. Subsequent categories are not
checked after a failure.

### Category 1 — Schema Validation
Confirm the overall structure of the input is present and parseable.
The input must be a well-formed structured object with the expected top-level keys.
A missing or unparseable structure is a VALIDATION_FAILURE.

### Category 2 — Required Field Validation
Confirm all required fields are present and non-null.
A missing required field is a VALIDATION_FAILURE identifying the field and the reason.

### Category 3 — Type Validation
Confirm all fields are the correct type.
A field with the wrong type is a VALIDATION_FAILURE identifying the field, the
received type, and the expected type.

### Category 4 — Value Validation
Confirm all values are within allowed ranges and meet value constraints.
Price must be numeric and greater than zero.
A value that fails a constraint is a VALIDATION_FAILURE identifying the field, the
received value, and the constraint violated.

### Category 5 — Source Validation
Confirm all source identifiers are non-empty and belong to the allowed source set.
An unrecognized or disallowed source is a VALIDATION_FAILURE identifying the source
value and the reason for rejection.

### Category 6 — Timestamp Validation
Confirm all observation timestamps are well-formed datetimes.
Confirm all timestamps fall within the freshness window defined in the spec.
A malformed timestamp is a VALIDATION_FAILURE.
A timestamp outside the freshness window is a PRECONDITION_FAILURE (the data is
structurally correct but stale for this execution context).

### Category 7 — Relationship Validation
Confirm structural relationships between entities are intact:
- every listing references a valid product in context,
- every observation references a valid listing in context,
- every observation source matches its referenced listing source.
A broken relationship is a VALIDATION_FAILURE identifying the entity reference and
the nature of the broken link.

### Category 8 — Comparison Eligibility Precondition
Confirm the input contains at least two observations from at least two distinct,
valid sources for the same product.
Failure of this check is a PRECONDITION_FAILURE — not a validation failure — because
the data may be individually valid but structurally insufficient for the pipeline.

---

## 7. Validation Rules

The following rules govern all validation behavior. These rules are derived directly
from the spec directives listed in Section 2 and must not be modified here.

### 7.1 No Silent Acceptance
Every field that fails a check must produce an explicit structured failure entry.
The validator must never silently accept a value that violates a rule.

### 7.2 No Silent Coercion
The validator must never convert a value to make it acceptable.
A string that looks like a number is not a number.
A string that looks like a datetime is not a datetime unless it parses correctly
per the defined format.
Coercion is the responsibility of the normalization stage, not the validator.

### 7.3 No Inference of Missing Values
If a required field is absent, the validator must reject the input.
It must not substitute a default, infer a value from context, or proceed without it.

### 7.4 No Partial Acceptance
The validator must not return VALID for an input where any check has failed.
Either the input is fully valid or it is not.
There is no partial-valid state.

### 7.5 Fail at the Earliest Violation
Validation must stop at the first failed category (see Section 6).
All errors within a failing category must be collected and returned together.
The validator must not surface errors from later categories until earlier categories pass.

### 7.6 Price Must Be Strictly Positive
A price value of zero is invalid. A negative price is invalid. Null is invalid.
Only a numeric value strictly greater than zero is acceptable.

### 7.7 Source Must Be Recognized
A source that is not in the allowed source set defined in the spec is invalid.
The validator must not accept unrecognized sources even if they are non-empty strings.

### 7.8 Freshness Is Mandatory When Defined
If the spec defines a freshness window, the validator must enforce it.
Observations outside the freshness window are not valid inputs for this pipeline
execution. Their failure is classified as PRECONDITION_FAILURE, not VALIDATION_FAILURE.
If the spec has not defined a freshness window, the validator must document this
explicitly rather than assume unlimited validity.

### 7.9 Relationships Must Be Verifiable Within Context
Relationship validation is scoped to the input context provided.
The validator does not call external systems to verify existence.
All entity references (product_ref, listing_ref) must resolve within the input context itself.
References to entities outside the input context are structural failures.

### 7.10 Duplicate Source Observations
If two observations in the input share the same source for the same product, the
validator must flag this as a VALIDATION_FAILURE. Only one observation per source
per product is permitted as input to the comparison pipeline.

---

## 8. Validation Output Structure

The validator must return exactly one structured output object for every execution.

The output must classify the result as one of three states: VALID, INVALID, or
PRECONDITION_FAILURE.

### 8.1 VALID Output

Returned when the input passes all eight validation categories.

Required fields:

- `result`: `"VALID"`
- `validated_at`: datetime — when validation completed
- `input_identity`: the stable identifier for this input context
- `observation_count`: integer — number of observations validated
- `source_count`: integer — number of distinct valid sources present

A VALID output authorizes the pipeline to proceed to Stage 2 (normalization).

### 8.2 INVALID Output

Returned when one or more fields fail Categories 1 through 7.

Required fields:

- `result`: `"INVALID"`
- `validated_at`: datetime
- `input_identity`: the stable identifier for this input context
- `failure_category`: the name of the category that failed (e.g., `"TYPE_VALIDATION"`)
- `errors`: a list of one or more structured error entries

Each error entry must include:

- `field`: the name of the field that failed
- `received_value`: the value received (redacted if sensitive)
- `reason`: a human-readable description of the failure
- `rule_violated`: the specific rule from Section 7 that was violated

A INVALID output halts the pipeline. No subsequent stage executes.
The input must be corrected before resubmission. The error is not retriable as-is.

### 8.3 PRECONDITION_FAILURE Output

Returned when the input is structurally valid but fails Category 6 (stale timestamps)
or Category 8 (insufficient observations for comparison).

Required fields:

- `result`: `"PRECONDITION_FAILURE"`
- `validated_at`: datetime
- `input_identity`: the stable identifier for this input context
- `precondition_failed`: a description of which precondition was not satisfied
- `reason`: a human-readable explanation

A PRECONDITION_FAILURE halts the pipeline. It is not a data error — the input may
become valid with fresh observations. Whether to retry depends on the precondition
(see Section 9).

---

## 9. Failure Classification

The validator distinguishes three and only three result states.

| Result | Meaning | Pipeline Action | Retriable |
|---|---|---|---|
| VALID | All checks passed | Proceed to Stage 2 | N/A |
| INVALID | One or more field-level checks failed | Halt immediately | No — input must be corrected |
| PRECONDITION_FAILURE | Input is valid but structurally insufficient for this execution | Halt immediately | Depends on precondition |

### Retriability of PRECONDITION_FAILURE

- **Stale observations**: may become retriable when fresh observations are available.
- **Insufficient source count**: may become retriable when additional source data is provided.
- **Missing rule set**: terminal — the rule set must be configured before retrying.
- **Missing alert threshold**: terminal — the threshold must be configured before retrying.

The validator must indicate in the output whether a precondition failure is
potentially retriable by including a `retriable` boolean field in the
PRECONDITION_FAILURE output.

---

## 10. Determinism Rules

The validator must behave deterministically in all circumstances.

1. The same input must always produce the same result classification.
2. The same input must always produce the same set of error entries, in a consistent order.
3. Validation must not depend on the current time, except when evaluating freshness
   windows — in which case the reference timestamp used must be passed explicitly as
   part of the execution context, not derived from the system clock at call time.
4. Validation must not depend on execution order or prior execution history.
5. Validation must not introduce randomness of any kind.
6. Validation results must not differ between the first run and the hundredth run on
   identical input.

---

## 11. Idempotency Considerations

The validator does not write to any persistent system.

Because it has no side effects, running it multiple times on the same input is
inherently safe. The same input always produces the same output.

However, the following rules apply to its use within the pipeline:

1. The pipeline must not run the validator more than once per input context per
   pipeline execution instance.
2. If a pipeline execution resumes after a prior PROCESSING_FAILURE, the validator
   must be re-executed from scratch — its prior result must not be assumed valid.
3. The validator's output must not be cached across pipeline execution instances.
   Freshness windows and source set membership may change between executions.

---

## 12. Logging and Audit Requirements

### Logging Requirements

The validator must emit a structured log entry at the following points:

- **Validation start**: input identity, execution context reference, timestamp.
- **Category entry**: the name of each validation category as it begins.
- **Validation end**: result classification, number of errors if any, timestamp.

For INVALID results, the log must include the failure category and a summary of
failing fields. It must not log raw sensitive values (prices, credentials).

For PRECONDITION_FAILURE results, the log must include which precondition failed
and whether the failure is retriable.

### Audit Requirements

The validator does not write audit records directly.
The audit record for validation outcome is written by Stage 8 of the pipeline,
using the structured output from the validator as its source.

The validator must therefore ensure its output contains enough context to support
a complete audit entry: result, identity, timestamp, and error detail.

---

## 13. What This Validator Must NOT Do

The following are explicitly forbidden:

- **Transform data.** The validator must not change any field value. It checks —
  it does not modify.
- **Normalize data.** Trimming whitespace, formatting prices, or canonicalizing
  source names is the responsibility of Stage 2 (normalization). The validator
  operates on the raw input as received.
- **Enrich data.** The validator must not add, supplement, or augment the input
  with data from any external source or internal lookup.
- **Infer missing values.** If a required field is absent, the validator rejects.
  It must not substitute defaults, derive values, or proceed without them.
- **Call external systems.** The validator must not query the database, call an API,
  or reach outside the input context to verify any field. All checks are performed
  against the data provided.
- **Apply business logic.** The validator does not evaluate whether a discrepancy
  exists, whether a score would be high, or whether an opportunity is interesting.
  That is the work of downstream stages.
- **Make AI-driven decisions.** No AI model may be invoked to determine whether
  a field is acceptable.
- **Produce partial results.** The validator must not return VALID alongside a
  list of warnings for fields that technically failed. Either the input is VALID or
  it is not.
- **Swallow exceptions.** Any unexpected error during validation must surface as an
  explicit exception — not be caught and returned as a silent VALID or empty result.
- **Produce different results for the same input.** Validation is deterministic.
  Any non-deterministic behavior is a defect.

---

## 14. Success Criteria

The validator is successful when:

1. A fully valid input returns a VALID result with all required output fields populated.
2. An input with a missing required field returns INVALID identifying the field and rule.
3. An input with a wrong field type returns INVALID identifying the field, received type,
   and expected type.
4. An input with a price of zero, null, or a negative value returns INVALID.
5. An input with an unrecognized source identifier returns INVALID.
6. An input with a malformed timestamp returns INVALID.
7. An input with observations outside the freshness window returns PRECONDITION_FAILURE
   with `retriable: true`.
8. An input with fewer than two distinct valid source observations returns
   PRECONDITION_FAILURE with the observation count and source count included.
9. An input with a broken entity relationship (e.g., observation referencing a
   non-existent listing) returns INVALID identifying the broken reference.
10. An input with duplicate observations from the same source for the same product
    returns INVALID.
11. Running the validator twice on the same input produces identical output both times.
12. Running the validator on a VALID input produces no error entries in the output.
13. All validation categories are independently testable with deterministic inputs.
14. No validation run calls an external system, database, or API.
15. No field value is modified, normalized, or inferred at any point during validation.

---

## 15. Non-Acceptance Conditions

The validator is not acceptable if any of the following are true:

- An invalid input (missing field, wrong type, out-of-range value) returns VALID.
- A structurally broken input (orphan listing, mismatched source) reaches Stage 2
  of the pipeline.
- Any field value is silently corrected, coerced, or defaulted during validation.
- The validator calls the database, an external API, or any system outside the input
  context to resolve a field.
- A PRECONDITION_FAILURE is returned for a condition that is actually a field-level
  validation error.
- A VALIDATION_FAILURE is returned for a condition that is actually a precondition
  (e.g., stale observations flagged as a field error instead of a structural failure).
- The validator returns different results for identical inputs on separate runs.
- An INVALID output is missing the field name, received value, or rule violated for
  any error entry.
- A PRECONDITION_FAILURE output is missing the `retriable` classification.
- Unit tests do not cover all three result classifications.
- Any validation exception is caught and suppressed rather than surfaced explicitly.
- The validator applies or invents a rule not traceable to the spec directives listed
  in Section 2.

Any of these conditions is a blocking defect. The validator must not be considered
complete while any non-acceptance condition is present.
