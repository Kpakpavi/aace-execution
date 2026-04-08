# Price Monitoring Acceptance Criteria

## 1. Purpose

This document defines the acceptance criteria for the Price Monitoring feature.

It specifies the exact conditions under which the feature is considered correct, complete, and working.

All criteria must be:

- testable
- deterministic
- observable
- aligned with requirements

---

## 2. Acceptance Philosophy

The feature is accepted only if:

- discrepancies are detected correctly
- noise is filtered out
- results are explainable
- behavior is repeatable
- failures are handled safely

“Looks correct” is not sufficient.
“Passes defined tests” is required.

---

## 3. Input Validation

The feature is accepted if:

1. Valid product, listing, and observation data is processed successfully
2. Missing required fields cause rejection or safe failure
3. Invalid data types are rejected
4. Invalid source associations are not processed
5. The system does not crash on malformed input

---

## 4. Comparison Eligibility

The feature is accepted if:

1. Only valid product-linked listings are compared
2. At least two valid price sources are required
3. Ineligible data is excluded from comparison
4. The system does not compare unrelated products
5. Eligibility rules are applied consistently

---

## 5. Price Comparison

The feature is accepted if:

1. Price values are correctly compared
2. Differences are calculated accurately
3. Comparison logic is consistent across runs
4. Same input produces same comparison result

---

## 6. Threshold Filtering

The feature is accepted if:

1. Differences below threshold are not surfaced
2. Differences above threshold are surfaced
3. Threshold rules are applied consistently
4. Threshold logic is deterministic

---

## 7. Discrepancy Detection

The feature is accepted if:

1. Meaningful discrepancies are detected
2. Non-meaningful differences are ignored
3. Each discrepancy includes required context:
   - product
   - sources
   - price values
   - difference
4. Results are reproducible

---

## 8. Explainability

The feature is accepted if:

1. Each discrepancy can be explained
2. Explanation includes:
   - what was compared
   - what rule was applied
   - why threshold was met
3. No discrepancy is returned without explanation

---

## 9. Noise Suppression

The feature is accepted if:

1. Insignificant price differences are not returned
2. Invalid or incomplete comparisons are ignored
3. Duplicate or redundant discrepancies are minimized

---

## 10. Determinism

The feature is accepted if:

1. Same inputs always produce same outputs
2. No randomness affects results
3. No hidden logic changes outcomes

---

## 11. Traceability

The feature is accepted if:

1. Inputs used for comparison can be traced
2. Evaluation time is recorded
3. Rule/threshold applied is identifiable
4. Results can be audited

---

## 12. Failure Handling

The feature is accepted if:

1. Invalid inputs do not crash the system
2. Failures are logged
3. System distinguishes:
   - no discrepancy
   - evaluation failure
4. Errors do not expose sensitive data

---

## 13. Downstream Compatibility

The feature is accepted if:

1. Output structure supports scoring
2. Outputs are consistent and structured
3. No ambiguous or incomplete results are produced

---

## 14. Minimum Test Scenarios

The feature must pass:

### Happy Path
- valid product
- valid listings
- valid discrepancy detected

### No Discrepancy Case
- valid inputs
- below-threshold difference

### Edge Case
- multiple listings
- borderline threshold

### Failure Case
- invalid input
- missing fields

---

## 15. Completion Criteria

The feature is complete only if:

- all criteria pass
- outputs are deterministic
- discrepancies are explainable
- system is testable
- no major requirement is unmet

---

## 16. Non-Acceptance Conditions

The feature must be rejected if:

- discrepancies are inconsistent
- outputs cannot be explained
- threshold logic is unclear
- invalid data produces results
- failures are silent

---

## 17. Open Questions

- What is the exact threshold value for MVP?
- Should borderline discrepancies be included or excluded?
- What minimum dataset is required for validation?

difference = |price_a - price_b|

#### Percentage Difference

percentage = (|price_a - price_b| / min(price_a, price_b)) * 100


The MVP must define which method is used (or both).

---

## 6. Threshold Rules

A discrepancy is valid only if it exceeds threshold.

### 6.1 Absolute Threshold

Example:
- threshold = $5
- difference must be >= 5

---

### 6.2 Percentage Threshold

Example:
- threshold = 10%
- percentage difference must be >= 10%

---

### 6.3 MVP Requirement

At least ONE threshold method must be implemented.

Threshold must be:

- explicit
- configurable (even if hardcoded initially)
- consistent across evaluations

---

## 7. Directionality (Optional for MVP)

The system may optionally track:

- which source is cheaper
- which source is more expensive

Example:
- buy low (Amazon)
- sell high (eBay)

If implemented:
- must be deterministic
- must be explainable

---

## 8. Noise Filtering Rules

The system must NOT create discrepancies when:

1. difference is below threshold
2. price values are missing or invalid
3. listings belong to unrelated products
4. currency mismatch without normalization
5. duplicate listings are compared
6. stale or invalid observations (if freshness is enforced)

---

## 9. Freshness Rule (Optional for MVP)

If enabled:

- only recent observations are valid
- stale data must be excluded

Example:
- only observations within last 24 hours

If not implemented:
- must be explicitly documented

---

## 10. Duplicate Handling

The system must:

- avoid duplicate discrepancy records
- ensure identical comparisons are not repeated

Example:
- A vs B should not be duplicated as B vs A

---

## 11. Result Construction

Each discrepancy must include:

- product_id
- listing_a_id
- listing_b_id
- price_a
- price_b
- absolute_difference
- percentage_difference (if used)
- threshold_used
- evaluation_timestamp

---

## 12. Determinism Rules

The system must:

- produce same results for same inputs
- avoid randomness
- avoid order-dependent outputs

---

## 13. Explainability Rules

Each discrepancy must answer:

- what was compared?
- what were the prices?
- what was the difference?
- what threshold was applied?
- why was it considered valid?

---

## 14. Failure Rules

The system must:

- skip invalid comparisons safely
- not crash on bad data
- log failures for debugging

---

## 15. MVP Constraints

The system must NOT:

- use AI to decide discrepancies
- infer relationships between unrelated products
- apply hidden scoring logic
- overfit rules to edge cases

---

## 16. Example Scenario

Product X:

- Listing A → $100
- Listing B → $115

Threshold:
- absolute = $10

Result:
- difference = $15
- discrepancy detected ✅

---

## 17. Non-Discrepancy Example

Product X:

- Listing A → $100
- Listing B → $103

Threshold:
- absolute = $5

Result:
- difference = $3
- no discrepancy ❌

---

## 18. Completion Criteria

The rules are complete when:

- discrepancies are detected correctly
- noise is filtered
- outputs are deterministic
- results are explainable
- rules are testable

---

## 19. Open Questions

- absolute vs percentage threshold?
- threshold values for MVP?
- freshness requirement?
- allowed source combinations?