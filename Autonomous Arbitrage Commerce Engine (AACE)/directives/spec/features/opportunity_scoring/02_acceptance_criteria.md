# Opportunity Scoring Acceptance Criteria

## 1. Purpose

This document defines the acceptance criteria for the Opportunity Scoring feature in the AACE MVP.

Its purpose is to specify the exact conditions under which the feature is considered correct, complete, deterministic, and ready for use.

The feature is not accepted because it produces scores.
It is accepted only if those scores are:

- correct,
- explainable,
- structured,
- repeatable,
- suitable for ranking and review.

---

## 2. Acceptance Philosophy

The Opportunity Scoring feature is accepted only if:

- valid discrepancies are scored correctly,
- invalid discrepancies are not scored,
- score outputs are deterministic,
- ranking is consistent,
- score explanations are preserved,
- failures are handled safely and visibly.

“Looks reasonable” is not sufficient.
“Passes defined validation criteria” is required.

---

## 3. Input Validation Acceptance

The feature is accepted if:

1. valid discrepancy inputs are accepted for scoring,
2. discrepancies missing required fields are rejected or fail safely,
3. invalid data types do not produce a score,
4. incomplete discrepancy records do not produce ambiguous outputs,
5. invalid scoring attempts do not crash the system.

The feature must not score data it cannot evaluate correctly.

---

## 4. Scoring Eligibility Acceptance

The feature is accepted if:

1. only valid discrepancy results are eligible for scoring,
2. scoring does not occur unless required discrepancy context exists,
3. discrepancy results that failed threshold validation are not scored,
4. invalid or ineligible discrepancy inputs are excluded consistently,
5. eligibility behavior is deterministic across repeated runs.

---

## 5. Score Calculation Acceptance

The feature is accepted if:

1. a score is computed for each valid eligible discrepancy,
2. the scoring formula is applied consistently,
3. the same valid input produces the same score,
4. score calculation does not depend on hidden heuristics,
5. score calculation uses only approved scoring factors.

If the scoring formula cannot be explained or repeated, the feature is not accepted.

---

## 6. Scoring Factor Acceptance

The feature is accepted if:

1. the primary scoring factor is applied correctly,
2. any secondary factors used in MVP are applied consistently,
3. scoring weights or factor contributions are explicit,
4. scoring factors are preserved in output or traceable context,
5. score inflation or suppression does not occur without defined rule basis.

If a factor affects score, that factor must be visible and explainable.

---

## 7. Score Range Acceptance

The feature is accepted if:

1. score outputs remain within the approved scoring range,
2. score scale is applied consistently,
3. higher-value discrepancies receive appropriately higher scores under the defined rule model,
4. score formatting does not create ambiguity.

If normalization is used, normalization behavior must be deterministic and documented.

---

## 8. Ranking Acceptance

The feature is accepted if:

1. opportunities can be ordered by score,
2. ranking is consistent across repeated evaluation runs,
3. equal-score cases are handled predictably,
4. ranking does not depend on unstable ordering behavior,
5. ranking remains compatible with review and reporting surfaces.

The feature must not produce arbitrary ordering for materially equivalent outputs.

---

## 9. Output Structure Acceptance

The feature is accepted if each scored opportunity includes, at minimum:

- opportunity reference or id,
- discrepancy reference,
- score,
- scoring factor context,
- timestamp context,
- status field or status-ready structure if defined.

Outputs must be structured and suitable for downstream use.

The feature is not accepted if score results are produced only as vague text.

---

## 10. Explainability Acceptance

The feature is accepted if every scored opportunity can answer:

- what discrepancy was scored,
- what score was assigned,
- what factors contributed,
- why this score is higher or lower than another comparable opportunity,
- whether any thresholding or weighting affected the result.

The feature is not accepted if:

- score exists without explanation,
- factor contribution is hidden,
- ranking cannot be justified.

---

## 11. Determinism Acceptance

The feature is accepted if:

1. the same valid discrepancy input always produces the same score,
2. the same scoring configuration always produces the same ranking,
3. no randomness affects outputs,
4. no hidden runtime AI logic affects score,
5. repeated evaluation does not produce drift for unchanged inputs.

Determinism is non-negotiable.

---

## 12. Traceability Acceptance

The feature is accepted if:

1. the score can be traced back to the discrepancy that produced it,
2. the contributing scoring factors are identifiable,
3. the evaluation time is preserved,
4. the scoring decision can be reviewed during debugging or audit,
5. score history or creation context is preserved sufficiently for MVP review needs.

---

## 13. Downstream Compatibility Acceptance

The feature is accepted if its outputs can be used by:

- opportunity review surfaces,
- reporting,
- audit/event systems,
- future status-management flows.

Compatibility requires:

1. structured outputs,
2. stable references,
3. predictable score meaning,
4. preserved explanation context.

---

## 14. Failure Handling Acceptance

The feature is accepted if:

1. invalid discrepancy inputs do not produce scores,
2. incomplete data results in safe failure or exclusion,
3. scoring failures are traceable,
4. the system distinguishes scoring failure from valid low-score outcomes,
5. failures do not expose unsafe internal details,
6. failure behavior is deterministic and reviewable.

A failed score calculation must not silently become a guessed score.

---

## 15. Minimum Test Scenarios

The feature must pass at least the following scenarios:

### Happy Path
- valid discrepancy input
- valid scoring factors
- score created successfully
- output ranked correctly

### Equal Score Case
- two valid discrepancies with equal scoring inputs
- ordering handled predictably

### Invalid Input Case
- missing required discrepancy field
- no score generated
- failure handled safely

### Low-Value Opportunity Case
- valid discrepancy input
- valid score generated
- score is lower than a stronger discrepancy under same rules

### Failure Case
- scoring rule input missing or invalid
- scoring fails safely
- failure is traceable

---

## 16. Completion Criteria

The Opportunity Scoring feature is complete only if:

1. valid discrepancies are scored deterministically,
2. scores are explainable,
3. opportunities can be ranked predictably,
4. invalid inputs do not produce misleading outputs,
5. outputs are structured for downstream use,
6. scoring behavior is independently testable,
7. scoring decisions are traceable.

---

## 17. Non-Acceptance Conditions

The feature must be rejected if any of the following occur:

- scores vary for identical inputs,
- score factors are hidden,
- ranking is unstable,
- invalid discrepancies are scored,
- score outputs cannot be explained,
- failures silently produce partial or guessed outputs,
- downstream consumers cannot use the output reliably.

---

## 18. Example Acceptance Scenario

### Scenario A — Strong Opportunity
- discrepancy is valid
- price difference is high
- scoring factors are complete
- score is high
- output ranks above weaker opportunities
- explanation shows why

Expected result:
- accepted

### Scenario B — Weak but Valid Opportunity
- discrepancy is valid
- price difference is small but above threshold
- scoring factors are complete
- score is low but valid
- explanation preserved

Expected result:
- accepted

### Scenario C — Invalid Discrepancy Input
- discrepancy reference exists
- required factor input missing
- scoring cannot complete safely

Expected result:
- no score created
- failure traceable
- no misleading output

---

## 19. Open Questions

- Should the MVP normalize scores to a fixed range such as 0–100?
- What tie-break rule should apply when scores are equal?
- Should freshness be part of the first scoring release or deferred?
- Which scoring factors are mandatory on day one versus immediately after MVP?