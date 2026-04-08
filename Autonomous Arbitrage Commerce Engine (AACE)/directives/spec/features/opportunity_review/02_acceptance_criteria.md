# Opportunity Review Acceptance Criteria

## 1. Purpose

This document defines the acceptance criteria for the Opportunity Review feature in the AACE MVP.

Its purpose is to specify the exact conditions under which the feature is considered correct, usable, secure, and complete.

The feature is not accepted simply because opportunities are visible.
It is accepted only if users can review opportunities safely, clearly, and consistently within approved access boundaries.

---

## 2. Acceptance Philosophy

The Opportunity Review feature is accepted only if:

- authorized users can view opportunity data,
- unauthorized users are blocked,
- opportunity details are clear and explainable,
- sorting and filtering behave consistently,
- status changes work correctly,
- failures are handled safely.

“Page loads” is not sufficient.
“Passes defined, testable review behavior” is required.

---

## 3. Authentication Acceptance

The feature is accepted if:

1. unauthenticated users cannot access protected opportunity views,
2. authenticated users can access only permitted opportunity review surfaces,
3. expired or invalid auth context is rejected safely,
4. protected review endpoints or pages do not expose data before access checks complete.

The feature must not rely on frontend-only protection.

---

## 4. Authorization Acceptance

The feature is accepted if:

1. role-based access is enforced consistently,
2. admin users can access approved full review capabilities,
3. manager users can access approved review capabilities within policy,
4. standard users cannot access restricted data or actions beyond their scope,
5. unauthorized attempts to access opportunity data are blocked safely,
6. unauthorized status-change attempts fail predictably.

The feature must not expose admin-only review behavior to lower-privilege roles.

---

## 5. Opportunity List Acceptance

The feature is accepted if:

1. authorized users can view a structured list of opportunities,
2. each list item includes required summary data,
3. list results are deterministic,
4. the same underlying data produces the same list ordering under the same filters and sort,
5. list view does not expose unauthorized fields,
6. empty-list cases are handled clearly and safely.

At minimum, each visible list item must include:

- opportunity id or stable reference,
- product reference or recognizable summary,
- score,
- opportunity status,
- timestamp or freshness-related summary where required.

---

## 6. Opportunity Detail Acceptance

The feature is accepted if:

1. authorized users can view a detailed opportunity record,
2. detail view includes discrepancy context,
3. detail view includes score and scoring explanation,
4. detail view includes relevant product/listing references,
5. detail view includes status,
6. not-found and forbidden cases are handled distinctly where appropriate.

The detail view must allow a reviewer to understand why the opportunity exists.

---

## 7. Explainability Acceptance

The feature is accepted if each reviewed opportunity clearly shows:

1. what product or listing context was evaluated,
2. what prices were compared,
3. what discrepancy was found,
4. what score was assigned,
5. what factors contributed to the score,
6. why the opportunity appears in its relative order.

The feature must be rejected if opportunity outputs appear as opaque score-only records.

---

## 8. Filtering Acceptance

The feature is accepted if:

1. filtering by approved fields works correctly,
2. the minimum MVP filters operate deterministically,
3. filters return only matching results,
4. filter application does not mutate underlying opportunity data,
5. filter combinations behave predictably,
6. invalid filter values fail safely.

At minimum, the MVP should support filtering by:

- score range,
- status,
- product reference or product identifier.

---

## 9. Sorting Acceptance

The feature is accepted if:

1. opportunities can be sorted by approved sort fields,
2. default sort order is clearly defined,
3. sorting is deterministic,
4. repeated evaluation under the same data returns the same ordering,
5. tie handling is stable.

At minimum, sorting should support:

- score,
- timestamp.

If score is the default sort, that default must remain consistent.

---

## 10. Status Management Acceptance

The feature is accepted if:

1. users with approved permissions can update opportunity status,
2. only valid statuses are accepted,
3. invalid status values are rejected,
4. invalid status transitions are rejected if transition rules exist,
5. status changes persist correctly,
6. status changes are traceable,
7. users without permission cannot update status.

At minimum, approved MVP statuses are:

- active,
- reviewed,
- dismissed.

The feature must not silently accept unsupported statuses.

---

## 11. Output Structure Acceptance

The feature is accepted if its responses or rendered views are structured and consistent.

This means:

1. list outputs use a consistent summary structure,
2. detail outputs use a consistent detailed structure,
3. score and discrepancy fields are not omitted unpredictably,
4. status and timestamps are represented consistently,
5. downstream consumers can rely on stable meaning.

The feature must not return vague or human-only representations that cannot be consumed reliably.

---

## 12. Determinism Acceptance

The feature is accepted if:

1. the same valid opportunity set produces the same visible ordering under the same sort/filter settings,
2. the same detail request produces the same opportunity content unless the underlying data changed,
3. no random ordering or hidden reshuffling occurs,
4. explanation fields remain consistent with the underlying score and discrepancy data.

Determinism is required for trust and usability.

---

## 13. Failure Handling Acceptance

The feature is accepted if:

1. invalid requests do not crash the system,
2. not-found opportunity requests return safe not-found behavior,
3. forbidden access returns safe forbidden behavior,
4. malformed filter or sort input fails safely,
5. missing or incomplete opportunity data is handled without exposing unsafe internals,
6. errors do not leak stack traces, secrets, or internal system details.

Failure behavior must distinguish between:

- no data,
- invalid request,
- unauthorized access,
- system failure.

---

## 14. Auditability Acceptance

The feature is accepted if important user review actions are traceable.

At minimum, this includes:

1. status update actions,
2. admin-level review actions where logged by policy,
3. protected access attempts where audit policy requires them.

The feature does not need to log every harmless read interaction in the MVP unless defined elsewhere, but important state-changing review actions must remain traceable.

---

## 15. Downstream Compatibility Acceptance

The feature is accepted if its outputs remain compatible with:

- reporting,
- audit/event systems,
- future dashboard expansion,
- future alerting or notification features.

Compatibility requires:

1. stable identifiers,
2. clear status semantics,
3. preserved score meaning,
4. structured discrepancy context.

---

## 16. Minimum Test Scenarios

The feature must pass at least the following scenarios:

### Happy Path
- authorized user views opportunity list
- opens opportunity detail
- sees discrepancy and score explanation
- updates status successfully

### Unauthorized Access Case
- unauthenticated or unauthorized user attempts access
- access is blocked safely

### Filter Case
- user filters by status or score
- returned results match filter correctly

### Sort Case
- user sorts by score or timestamp
- ordering is stable and correct

### Invalid Status Case
- user submits unsupported status
- request fails safely
- no invalid update is persisted

### Not Found Case
- user requests missing opportunity id
- safe not-found behavior returned

---

## 17. Completion Criteria

The Opportunity Review feature is complete only if:

1. authorized users can review opportunities,
2. explanations are visible and understandable,
3. sorting and filtering work predictably,
4. status updates work correctly,
5. access control is enforced,
6. outputs are structured and stable,
7. failure handling is safe,
8. critical behavior is testable.

---

## 18. Non-Acceptance Conditions

The feature must be rejected if any of the following occur:

- unauthorized users can see protected opportunity data,
- opportunity details are missing required explanation context,
- sorting is unstable,
- filtering returns incorrect results,
- invalid statuses are accepted,
- status changes are not traceable,
- errors expose unsafe internal details,
- opportunity review output is ambiguous or inconsistent.

---

## 19. Example Acceptance Scenarios

### Scenario A — Valid Review Flow
- manager logs in
- views ranked opportunities
- opens one opportunity
- sees discrepancy details and score breakdown
- marks it reviewed

Expected result:
- accepted

### Scenario B — Unauthorized User Attempt
- unauthenticated user tries to open opportunity detail
- access is blocked

Expected result:
- accepted

### Scenario C — Invalid Status Update
- authenticated user submits unsupported status value
- system rejects update safely
- previous status remains unchanged

Expected result:
- accepted

### Scenario D — Opaque Opportunity Output
- detail view shows only a score and status
- discrepancy context and scoring factors missing

Expected result:
- rejected

---

## 20. Open Questions

- Should pagination be mandatory in the first MVP release?
- What default sort order should apply on first load?
- Which role, if any, may dismiss opportunities in MVP?
- Should read-only review access and state-changing review access be separated more strictly in the first release?