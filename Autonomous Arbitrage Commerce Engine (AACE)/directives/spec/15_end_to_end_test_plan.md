# AACE MVP End-to-End Test Plan

## 1. Purpose

This document defines the end-to-end test plan for the AACE MVP.

It specifies:

- the full system flows that must be validated end-to-end,
- the test scenarios required for each flow,
- the expected inputs, outputs, and behaviors,
- the acceptance bar for each scenario.

End-to-end tests validate that the entire system works together correctly, not just individual components in isolation.

---

## 2. End-to-End Testing Principles

End-to-end tests must:

- simulate realistic user or system flows,
- exercise the full stack from API or trigger to data storage and output,
- use controlled, known test data,
- be deterministic and repeatable,
- never touch production systems or live marketplace APIs.

End-to-end tests must NOT:

- replace unit or integration tests,
- be written without a defined expected output,
- depend on timing, randomness, or live external data.

---

## 3. Core End-to-End Flows

### Flow 1: User Authentication

#### Steps
1. User submits valid credentials.
2. System returns an authenticated session or token.
3. User accesses a protected resource.
4. System allows access.

#### Expected Outcome
- Access granted to the authenticated user.
- Protected resources visible according to the user's role.

#### Negative Case
- Invalid credentials submitted.
- System rejects authentication.
- No access granted.

---

### Flow 2: Product Ingestion

#### Steps
1. Valid product and listing data is submitted to the ingestion endpoint.
2. System validates the input.
3. System normalizes and stores the product and listing records.
4. Ingestion outcome is logged.

#### Expected Outcome
- Product and listing records exist in the database.
- Ingestion event is logged.

#### Negative Case
- Invalid or malformed product data submitted.
- System rejects the input with a clear error.
- No partial records created.

---

### Flow 3: Price Observation Recording

#### Steps
1. Marketplace adapter fetches pricing data.
2. Price observation is stored for the relevant product and marketplace.
3. Observation is linked to the correct product record.

#### Expected Outcome
- Price observation record exists in the database.
- Observation is correctly associated with the product and marketplace.

#### Negative Case
- Adapter returns invalid or missing price data.
- System handles the failure gracefully.
- No corrupt observation record is created.

---

### Flow 4: Discrepancy Detection

#### Steps
1. Discrepancy detection job runs against stored price observations.
2. System evaluates observations using defined discrepancy rules.
3. Qualifying discrepancies are identified.
4. Discrepancy detection event is logged.

#### Expected Outcome
- Discrepancies meeting the threshold are identified.
- No false positives below the threshold.
- Detection results are traceable to input observations.

#### Negative Case
- Price observations present but none meet the discrepancy threshold.
- System produces no discrepancy records.
- No false positives.

---

### Flow 5: Opportunity Scoring

#### Steps
1. Discrepancy records are passed to the scoring engine.
2. Scoring engine evaluates each discrepancy using defined scoring rules.
3. Opportunity records are created with scores and explanations.

#### Expected Outcome
- Opportunity records exist for each qualifying discrepancy.
- Each opportunity includes a score and explanation.
- Scoring is deterministic (same inputs produce same scores).

#### Negative Case
- Discrepancy records exist but none meet the scoring threshold.
- System produces no opportunity records (or records with score below threshold).
- No scoring logic errors.

---

### Flow 6: Alert Generation

#### Steps
1. High-scoring opportunities trigger alert generation.
2. Alert records are created and associated with the opportunity.
3. Alert event is logged.

#### Expected Outcome
- Alert records exist for qualifying opportunities.
- Each alert references the correct opportunity.
- No duplicate alerts for the same opportunity.

#### Negative Case
- Opportunity exists but score is below alert threshold.
- No alert generated.

---

### Flow 7: Dashboard and Reporting Access

#### Steps
1. Authenticated user accesses the dashboard.
2. Dashboard displays summary metrics, recent opportunities, and alerts.
3. User accesses a specific report.
4. Report returns structured, accurate data.

#### Expected Outcome
- Dashboard renders correctly with accurate data.
- Report returns correct results for the requested parameters.
- Role-based access is enforced.

#### Negative Case
- Unauthenticated user attempts dashboard access.
- System rejects the request.
- No data returned.

---

### Flow 8: Full Pipeline End-to-End

#### Steps
1. User authenticates.
2. Product and listing data is ingested.
3. Price observations are recorded.
4. Discrepancy detection runs.
5. Opportunity scoring runs.
6. Alert generation runs.
7. User views opportunities and alerts on the dashboard.

#### Expected Outcome
- All steps complete successfully.
- Opportunities and alerts are visible to the authenticated user.
- All events are logged and traceable.
- Determinism: repeating the flow with the same data produces the same result.

---

## 4. Test Data Requirements

Each end-to-end scenario must use:

- at least one product with multiple marketplace listings,
- at least one valid discrepancy case,
- at least one non-discrepancy case,
- at least one invalid input case,
- known-good expected outputs for each scenario.

Test data must be version-controlled and independent of production data.

---

## 5. Environment Requirements

End-to-end tests must run:

- against a local or CI test environment,
- using mock marketplace adapters,
- against a clean or seeded test database,
- with test credentials only.

End-to-end tests must never run against the production environment.

---

## 6. Pass/Fail Criteria

Each scenario passes if:

- expected outputs match actual outputs,
- no unexpected errors occur,
- all events are logged correctly,
- behavior is deterministic across runs.

Each scenario fails if:

- outputs are incorrect or missing,
- unexpected errors occur,
- behavior differs between runs with the same input,
- access control is violated.

---

## 7. Regression Requirements

After any change to core logic, the full end-to-end test suite must be rerun.

A regression is detected if:

- a previously passing scenario now fails,
- output values change unexpectedly,
- performance degrades significantly.

---

## 8. Reporting Test Results

Test results must be:

- logged to CI output,
- reviewable by the development team,
- stored as artifacts for failed runs.

---

## 9. Open Questions

- Which CI tool runs the end-to-end test suite?
- Should end-to-end tests be gated on every pull request or only on specific branches?
- What is the maximum acceptable end-to-end test suite duration?
- Are there scenarios that require manual validation in addition to automated tests?
