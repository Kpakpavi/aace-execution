# Alerts & Notifications Rules

## 1. Purpose

This document defines the deterministic rules for generating and handling notifications in the AACE MVP.

It specifies:

- when a notification should be created,
- when a notification must not be created,
- how duplicate notifications are prevented,
- what information a notification must contain,
- how notification behavior remains controlled and explainable.

These rules govern notification logic only.
They do not define external delivery integrations such as email or SMS.

---

## 2. Rule Philosophy

Notification behavior must prioritize:

- usefulness over volume,
- clarity over cleverness,
- determinism over dynamic heuristics,
- signal quality over engagement noise.

The system must avoid:

- spamming users,
- sending alerts for low-value opportunities,
- generating duplicate notifications,
- creating notifications that cannot be explained.

A missed low-value notification is preferable to a noisy or misleading notification.

---

## 3. Notification Trigger Model

A notification may be created only when all required trigger conditions are satisfied.

For the MVP, the default trigger model is:

1. a valid opportunity exists,
2. the opportunity is newly created or newly becomes eligible under an approved trigger rule,
3. the opportunity score meets or exceeds the configured alert threshold,
4. no equivalent notification already exists for the same opportunity and trigger condition.

If any required condition fails, no notification should be created.

---

## 4. Required Conditions

A notification can only be generated if all of the following are true:

1. the opportunity record is valid,
2. the opportunity has a stable identifier,
3. the opportunity has a valid score,
4. the opportunity status is eligible for notification,
5. the score meets or exceeds the configured threshold,
6. duplicate-prevention rules do not block generation.

If any of these conditions are missing or invalid, notification generation must stop safely.

---

## 5. Score Threshold Rule

The MVP must use an explicit score threshold for notification eligibility.

### Rule

A notification is valid only if:

- `opportunity.score >= notification_threshold`

### Requirements

- the threshold must be explicitly defined,
- the threshold must be consistent across evaluation runs,
- the threshold must not change silently,
- the threshold must be traceable in explanation or configuration context.

If the threshold is missing or invalid, notification generation must fail safely.

---

## 6. New Opportunity Rule

For MVP, notifications should be triggered on creation of a qualifying opportunity.

### Rule

A notification should be created when:

- a qualifying opportunity is first created,
- and it passes threshold,
- and it has not already been notified under the same rule.

This keeps MVP behavior simple and controlled.

---

## 7. Update Trigger Rule (Optional for MVP)

Notifications for updated opportunities are optional and must not be assumed unless explicitly enabled.

If update-trigger behavior is introduced, it must define:

- what type of update qualifies,
- whether crossing the threshold upward triggers a notification,
- whether status changes can trigger a notification,
- how duplicates are prevented.

If update-trigger behavior is not implemented, only creation-based notification is valid for MVP.

---

## 8. Eligible Opportunity Status Rule

Notifications should only be created for approved statuses.

For MVP, the default eligible status is:

- `active`

Notifications should not be created for opportunities already marked:

- `dismissed`
- `reviewed`

unless a future rule explicitly allows it.

---

## 9. Duplicate Prevention Rules

The system must prevent duplicate notifications for the same opportunity under the same condition.

### Minimum Rule

A notification must not be created if a prior notification already exists for:

- the same opportunity,
- the same notification type,
- the same trigger condition.

### Practical Meaning

The system must avoid:

- creating the same notification twice during repeated processing,
- re-emitting notification on retry without an explicit reason,
- notifying again just because the same opportunity was re-read.

Duplicate prevention is mandatory.

---

## 10. Notification Identity Rule

Each notification should have a stable identity or uniqueness basis.

At minimum, notification uniqueness should consider:

- opportunity id,
- notification type,
- trigger condition,
- generation context if needed.

This rule exists so retries and repeated evaluations do not create duplicate records.

---

## 11. Notification Content Rules

Each notification must contain enough information to be useful and reviewable.

At minimum, a notification must include:

- notification id or stable reference,
- opportunity id,
- score,
- concise summary of the discrepancy,
- reason it was triggered,
- timestamp,
- notification status if applicable.

A notification must not be just “something happened.”
It must be understandable on its own.

---

## 12. Notification Message Rules

The message or summary shown to a user must clearly communicate:

1. what opportunity triggered the notification,
2. why the notification was created,
3. what score or threshold condition was met,
4. enough context to decide whether review is warranted.

### Example Pattern

- “New opportunity detected for Product X. Score 82 exceeded alert threshold 70.”

The exact wording may vary, but the meaning must remain explicit.

---

## 13. Noise Reduction Rules

The notification system must reduce noise.

It must not create notifications when:

1. score is below threshold,
2. opportunity data is incomplete,
3. opportunity status is ineligible,
4. the same opportunity has already triggered the same notification condition,
5. the notification would add no new actionable value under MVP rules.

MVP notification behavior should be conservative.

---

## 14. Determinism Rules

Notification behavior must be deterministic.

Given the same opportunity input and the same notification rules, the system must produce the same notification outcome.

This means:

- same eligible opportunity → same notification decision,
- same ineligible opportunity → same suppression decision,
- no randomness in trigger logic,
- no hidden user-targeting or engagement heuristics.

---

## 15. Explainability Rules

Every notification must be explainable.

It must be possible to answer:

- why was this notification created?
- what opportunity triggered it?
- what threshold was met?
- why was it allowed or suppressed?

If the system cannot explain why a notification was generated, the rule set is incomplete.

---

## 16. Failure Rules

Notification generation must fail safely.

If notification logic cannot complete because of:

- missing threshold,
- invalid opportunity score,
- missing opportunity identifier,
- persistence failure,
- duplicate-check failure,
- processing failure,

then:

- no misleading notification should be emitted,
- failure should be traceable,
- partial ambiguous output should be avoided.

Failure must never silently become a valid notification.

---

## 17. Retry Rules

If retries are used for notification generation, they must remain safe.

Retries may be allowed only if:

- the original attempt failed for a transient reason,
- duplicate-prevention rules still apply,
- retry behavior is traceable.

Retries must not create multiple notifications for the same event.

---

## 18. Delivery Scope Rule

For MVP, notification logic may create:

- stored notification records,
- retrievable notification outputs,
- structured log events.

The MVP does not require external delivery systems such as:

- email,
- SMS,
- push notifications,
- Slack or webhook delivery.

Those may be added later, but notification rules must not assume them.

---

## 19. User Targeting Rule

If the MVP assigns notifications to users, the rule must be explicit.

At minimum, assignment behavior must define:

- which authenticated user or role can see the notification,
- whether notifications are global or scoped,
- whether admin/manager/user visibility differs.

If targeting is not yet implemented, notification visibility must still remain secure and role-aware.

---

## 20. Examples

### Example A — Valid Notification
- opportunity score = 82
- threshold = 70
- status = active
- no prior notification exists

Expected result:
- notification created

### Example B — Below Threshold
- opportunity score = 61
- threshold = 70
- status = active

Expected result:
- no notification created

### Example C — Duplicate Case
- opportunity score = 82
- threshold = 70
- identical notification already exists

Expected result:
- no duplicate notification created

### Example D — Ineligible Status
- opportunity score = 90
- status = dismissed

Expected result:
- no notification created

---

## 21. Completion Criteria

The notification rules are complete only if:

1. trigger conditions are explicit,
2. threshold behavior is explicit,
3. duplicate prevention is explicit,
4. content requirements are explicit,
5. failure behavior is explicit,
6. notification decisions are deterministic,
7. notification behavior is explainable.

---

## 22. Non-Acceptance Conditions

The notification rules must be rejected if:

- notifications can trigger below threshold,
- duplicate notifications are possible without explicit exception,
- ineligible statuses can generate notifications,
- message content is vague or insufficient,
- rule behavior depends on hidden logic,
- failures silently generate partial or ambiguous outputs.

---

## 23. Open Questions

- What exact score threshold should MVP use?
- Should notifications be visible to all authorized users or only selected owners?
- Should threshold-crossing on update trigger a notification in a later phase?
- Should notification status tracking be added in MVP or immediately after MVP?