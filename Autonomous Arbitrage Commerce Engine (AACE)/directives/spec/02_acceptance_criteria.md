# AACE MVP Acceptance Criteria

## 1. Purpose

This document defines the explicit conditions that must be met for the AACE MVP to be considered complete and working.

Acceptance criteria must be:

- testable,
- observable,
- unambiguous,
- aligned with requirements,
- verifiable without guessing.

If a requirement cannot be validated through these criteria, it is incomplete.

---

## 2. Acceptance Philosophy

The MVP is considered successful only if:

- system behavior is deterministic,
- outputs are explainable,
- access is controlled,
- failures are handled intentionally,
- results can be audited and tested.

“Looks correct” is not sufficient.
“Works under defined tests” is required.

---

## 3. Authentication & Access Control

The system is accepted if:

1. A user can create or be assigned an account.
2. A user can successfully authenticate using the approved method.
3. Invalid authentication attempts are rejected.
4. Protected routes cannot be accessed without authentication.
5. Role-based access is enforced:
   - admin can access admin functions,
   - manager can access allowed business views,
   - user is restricted to permitted views only.
6. Unauthorized access attempts are blocked.
7. Authentication-related events are recorded safely.
8. No credentials or secrets are exposed in logs or responses.

---

## 4. Data Ingestion

The system is accepted if:

1. Valid product/listing input is accepted and stored.
2. Invalid or malformed input is rejected or flagged.
3. Required fields are enforced.
4. Data is normalized into a consistent internal format.
5. Source context (origin of data) is preserved.
6. Duplicate or conflicting inputs are handled predictably.
7. Ingestion failures are visible and traceable.
8. The system can process at least one complete ingestion flow end-to-end.

---

## 5. Product & Listing Management

The system is accepted if:

1. Products can be uniquely identified.
2. Listings can be associated with products.
3. Multiple listings per product are supported.
4. Listings include identifiable source information.
5. Price-related fields are stored and retrievable.
6. Product and listing relationships are consistent and queryable.

---

## 6. Price Observation Handling

The system is accepted if:

1. Price observations can be recorded.
2. Each observation includes:
   - product or listing reference,
   - price value,
   - source,
   - timestamp.
3. Observations are retrievable for evaluation.
4. Observations support discrepancy detection.
5. The system can store enough history to support testing and audit.

---

## 7. Price Discrepancy Detection

The system is accepted if:

1. Price comparisons can be performed across at least two sources.
2. Discrepancy rules are applied consistently.
3. Insignificant price differences are not flagged as opportunities.
4. Meaningful discrepancies are detected reliably.
5. The same inputs produce the same discrepancy result.
6. Each detected discrepancy can be explained using defined rules.
7. Discrepancy logic can be tested independently of UI.

---

## 8. Opportunity Scoring

The system is accepted if:

1. Opportunities are generated from detected discrepancies.
2. Each opportunity includes:
   - associated product/listings,
   - relevant price data,
   - computed score.
3. Scoring is deterministic.
4. Scoring factors are preserved and visible.
5. Opportunities can be ranked or prioritized.
6. The scoring model can be explained in plain language.
7. The same input produces the same score.

---

## 9. Opportunity Review

The system is accepted if:

1. Authorized users can access opportunity outputs.
2. Each opportunity shows:
   - discrepancy details,
   - source data,
   - score,
   - relevant factors.
3. Unauthorized users cannot access protected data.
4. Opportunities are presented in a structured format (API or UI).
5. Users can distinguish between valid and invalid or stale opportunities where supported.

---

## 10. Reporting

The system is accepted if:

1. The system provides basic reporting on:
   - number of opportunities,
   - recent activity,
   - distribution of scores.
2. Reports are accessible only to authorized roles.
3. Reported data is consistent with stored data.
4. Reports do not expose sensitive information improperly.

---

## 11. Audit & Event Logging

The system is accepted if:

1. Key system actions are recorded, including:
   - ingestion events,
   - evaluation events,
   - authentication events,
   - important user actions.
2. Logs include timestamps and context.
3. Logs allow reconstruction of:
   - what happened,
   - when it happened,
   - what data was involved.
4. Sensitive data is not logged unsafely.
5. Logs can support debugging and evaluation.

---

## 12. Failure Handling

The system is accepted if:

1. Invalid inputs do not crash the system.
2. Failures are surfaced clearly.
3. Partial or inconsistent states are avoided where possible.
4. Retriable vs non-retriable failures are distinguishable where applicable.
5. The system does not silently ignore critical failures.
6. Errors do not expose sensitive internal details to users.

---

## 13. Determinism

The system is accepted if:

1. Given the same valid inputs and rules, the system produces the same outputs.
2. Discrepancy detection results are repeatable.
3. Scoring results are repeatable.
4. Access control decisions are consistent.
5. Any time-based behavior is explicitly defined.

---

## 14. Security

The system is accepted if:

1. All protected routes require authentication.
2. Role-based access is enforced correctly.
3. Passwords are not stored in plaintext.
4. Secrets are not present in the repository.
5. Sensitive data is not exposed in logs or responses.
6. Unauthorized access attempts are blocked.

---

## 15. Test Coverage

The system is accepted if:

1. Unit tests exist for:
   - discrepancy logic,
   - scoring logic,
   - validation rules.
2. Integration tests exist for:
   - ingestion flow,
   - authentication flow,
   - evaluation flow.
3. End-to-end tests validate:
   - input → discrepancy → scoring → output.
4. Tests cover:
   - happy path,
   - edge cases,
   - failure scenarios,
   - retry behavior where applicable.

---

## 16. Minimum End-to-End Scenario

The MVP is accepted if the following scenario works:

1. A user authenticates successfully.
2. Product/listing data is ingested.
3. Price observations are recorded.
4. A discrepancy is detected.
5. An opportunity is generated and scored.
6. The user can view the opportunity.
7. The system can explain how the result was produced.
8. All steps are traceable via logs or stored records.

---

## 17. Completion Criteria

The MVP is considered complete only if:

- all required flows work end-to-end,
- acceptance criteria are met without manual overrides,
- system behavior is testable and repeatable,
- no critical requirement is unmet,
- major known risks are documented,
- the system behaves consistently under defined scenarios.

---

## 18. Non-Acceptance Conditions

The MVP must be rejected if:

- outputs cannot be explained,
- behavior is inconsistent or non-deterministic,
- access control is bypassable,
- failures are hidden or silent,
- data cannot be traced,
- tests cannot validate core behavior.

---

## 19. Open Questions

- What minimum dataset is required to validate discrepancy detection effectively?
- What score threshold defines a “valid” opportunity in MVP?
- Which failure scenarios must be mandatory in first test coverage?