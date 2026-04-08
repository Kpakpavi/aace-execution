# AACE MVP Constraints

## 1. Purpose

This document defines the non-negotiable constraints and guardrails for the AACE MVP.

Constraints exist to prevent unsafe, ambiguous, or overly broad implementation.
They are not optional suggestions.
They define the limits within which the MVP must be designed, built, tested, and operated.

If a proposed implementation conflicts with this document, the implementation must be revised or escalated.

---

## 2. Constraint Philosophy

The AACE MVP must be built under controlled conditions.

This means:

- no blind automation,
- no undefined autonomy,
- no hidden system behavior,
- no implementation shortcuts that reduce safety or auditability,
- no premature complexity that makes the system harder to reason about.

When there is tension between speed and control, control wins.

When there is tension between convenience and correctness, correctness wins.

When there is tension between ambition and determinism, determinism wins.

---

## 3. Priority Order

When constraints conflict with lower-level preferences, the following order governs decision-making:

1. safety,
2. correctness,
3. determinism,
4. auditability,
5. security,
6. maintainability,
7. explainability,
8. operational simplicity,
9. performance,
10. delivery speed.

No lower-priority objective may justify violating a higher-priority constraint.

---

## 4. Scope Constraints

## 4.1 MVP Scope Must Remain Narrow

The MVP must remain focused on:

- product/listing data ingestion,
- price discrepancy detection,
- deterministic opportunity scoring,
- protected opportunity review,
- basic reporting,
- auditability and traceability.

The MVP must not expand into a broad commerce automation platform before the core loop is proven.

---

## 4.2 Explicitly Out of Scope

The following are out of scope unless separately approved:

- autonomous purchasing,
- automated checkout or fulfillment,
- automated repricing on live marketplaces,
- broad marketplace support from day one,
- advanced forecasting or recommendation engines,
- black-box AI decision systems for runtime business logic,
- microservices-first decomposition,
- enterprise IAM, SSO, or advanced policy engines,
- large-scale workflow automation across many external tools,
- uncontrolled agent behavior.

Any attempt to quietly introduce these capabilities violates the MVP boundary.

---

## 4.3 No Silent Scope Expansion

Features may not be introduced simply because they seem useful, interesting, or easy to add.

Any new feature that materially changes:

- system behavior,
- system risk,
- architectural complexity,
- data sensitivity,
- external dependencies,
- compliance posture,

must be explicitly specified before implementation.

---

## 5. Architecture Constraints

## 5.1 Modular Monolith Constraint

The MVP must follow a modular monolith architecture.

This means:

- one primary application/system boundary,
- one clear system of record,
- visible internal domain boundaries,
- no premature service fragmentation.

The MVP must not be designed as distributed microservices unless a later approved decision replaces this constraint.

---

## 5.2 Layer Separation Constraint

The system must preserve clear separation between:

1. directives/specification,
2. Claude orchestration/planning,
3. deterministic runtime execution.

Claude may assist planning, explanation, and controlled generation.
Claude must not become the direct runtime executor of core business logic.

Business logic must remain in deterministic application code and scripts.

---

## 5.3 No Mixed Responsibility Layers

No file, service, or workflow should blur these boundaries by combining:

- specification and execution,
- runtime business logic and planning instructions,
- privileged operations and public access logic,
- scoring logic and untraceable AI reasoning.

Responsibilities must remain visible and teachable.

---

## 6. Data Constraints

## 6.1 Relational System of Record

Core business data must be modeled explicitly in a relational system of record.

The MVP must not rely primarily on:

- unstructured blobs,
- opaque agent memory,
- spreadsheet-based operational truth,
- undocumented JSON payloads as the main business model.

Bounded metadata or traces may be stored flexibly, but core entities must remain explicit and queryable.

---

## 6.2 Required Data Domains

The MVP must preserve explicit support for at least:

- users,
- roles/access relationships,
- products,
- marketplace listings,
- price observations,
- opportunity evaluations,
- audit/event records.

No implementation may skip these domains and still claim MVP completeness.

---

## 6.3 Selective Raw Data Retention

Raw source payloads may be retained selectively when helpful for:

- audit,
- debugging,
- replay,
- investigation.

However, the MVP must not store source payloads blindly or indefinitely without purpose.
Retention must be intentional and bounded.

---

## 6.4 No Secret Storage in Repo

Secrets, credentials, API keys, tokens, and sensitive environment values must never be committed to the repository.

This includes:

- `.env` contents,
- marketplace credentials,
- test secrets,
- copied production-like credentials.

Placeholder values and local examples must be clearly non-sensitive.

---

## 7. Security Constraints

## 7.1 Least Privilege

Least privilege is the default rule.

Users, services, and admin surfaces must receive only the minimum access required to perform their function.

No role should receive broad or implicit access without justification.

---

## 7.2 Protected Surface Constraint

All protected routes, dashboards, and sensitive APIs must require authentication and authorization.

No implementation may assume “internal means safe.”

Administrative capabilities must remain explicitly protected.

---

## 7.3 Safe Logging Constraint

Logs must not expose sensitive information unsafely.

The MVP must avoid logging:

- plaintext passwords,
- secrets,
- full credential payloads,
- unnecessary personal data,
- sensitive reset or auth details.

Logs should preserve useful debugging context without becoming a data leak.

---

## 7.4 Credential Handling Boundary

If future marketplace credentials are introduced, they must be:

- stored securely,
- access-controlled,
- separated from normal application flow,
- excluded from repository storage,
- handled through explicitly approved mechanisms.

Marketplace credential management is not assumed to be a first-MVP requirement unless approved.

---

## 8. Determinism Constraints

## 8.1 Deterministic Business Logic

Core runtime logic for:

- validation,
- discrepancy detection,
- scoring,
- access control,
- status transitions,

must be deterministic.

Given the same valid inputs and rules, the system should produce the same outputs.

---

## 8.2 No Black-Box Runtime Decisions

The MVP must not depend on opaque AI outputs for core business decisions that affect:

- whether an opportunity exists,
- how it is scored,
- who may access data,
- what state transitions occur.

AI assistance may support planning or explanation, but not replace deterministic runtime rules for core business operations.

---

## 8.3 Explicit Time-Based Behavior Only

If any behavior changes based on time, freshness, expiration, or retention windows, that behavior must be explicitly defined.

Implicit time assumptions are not allowed.

---

## 9. Auditability Constraints

## 9.1 Traceability of Important Actions

The system must preserve enough information to trace:

- what was ingested,
- what was evaluated,
- what rules were applied,
- what outputs were created,
- what user or system action caused significant changes.

Important actions must not become invisible.

---

## 9.2 Explainable Outputs

Opportunity outputs must be explainable in plain language.

A reviewer should be able to answer:

- why this opportunity exists,
- what data produced it,
- what rules affected it,
- why it ranks as it does.

Any implementation that produces useful-looking outputs without explanation violates this constraint.

---

## 9.3 No Hidden State Mutation

Critical state changes must not occur invisibly.

If the system changes business-significant state, that change must be:

- deliberate,
- observable,
- reviewable,
- attributable.

---

## 10. Operational Constraints

## 10.1 Simplicity Over Premature Scale

The MVP must prefer a simpler operational model over distributed complexity.

This means avoiding premature introduction of:

- many services,
- many databases,
- unnecessary queues,
- advanced orchestration platforms,
- infrastructure that exceeds MVP needs.

Operational sophistication must be earned by demonstrated need.

---

## 10.2 Local Development Must Remain Feasible

The system must remain understandable and executable in a normal local development workflow.

A contributor should be able to:

- understand major modules,
- run the application locally,
- test core flows,
- inspect outputs,
- debug failures,

without requiring enterprise-scale infrastructure from day one.

---

## 10.3 No Destructive Operations Without Approval

No destructive script or system behavior may be introduced without explicit approval.

This includes:

- deleting production-like data,
- destructive migrations,
- irreversible transformations,
- automatic cleanup jobs with destructive effects.

For intern-safe workflows, destructive actions must always be explicit and reviewable.

---

## 11. Testing Constraints

## 11.1 Testing Is Mandatory

The MVP must not be considered complete without testing.

At minimum, testing must cover:

- unit-level deterministic logic,
- integration-level critical flows,
- end-to-end core scenarios,
- happy paths,
- edge cases,
- failure paths,
- retry behavior where applicable.

“No time for tests” is not an acceptable exception.

---

## 11.2 Core Logic Must Be Independently Testable

Discrepancy detection and opportunity scoring must be testable independently of UI concerns.

Protected access behavior must also be testable independently of presentation details.

---

## 11.3 Failure Paths Must Be Intentional

Failure handling cannot be accidental.

Critical flows must define:

- invalid input behavior,
- retriable failure behavior where relevant,
- non-retriable failure behavior,
- user-facing error boundaries,
- operational traceability.

---

## 12. Workflow Constraints

## 12.1 One Intentional Change at a Time

Work should proceed in small, deliberate steps.

Large refactors, broad edits, or multi-domain changes without explicit approval are not allowed.

The default mode is:
- define scope,
- make one change,
- review it,
- test it,
- then continue.

---

## 12.2 No Hidden Changes

Every meaningful change must be visible and reviewable.

No assistant-generated change should be accepted blindly.
If a contributor cannot explain a change, it should not be kept.

---

## 12.3 Specification Before Implementation

No non-trivial implementation should begin without adequate specification.

For high-risk, multi-file, multi-session, or architecture-shaping work, the system must have:

- a self-contained problem definition,
- acceptance criteria,
- constraints,
- decomposition,
- evaluation design.

If these are missing, specification work takes priority over code generation.

---

## 12.4 Escalate Instead of Guessing

When context is missing, constraints conflict, or a change increases risk beyond defined boundaries, the correct behavior is escalation, not guessing.

Guessing under uncertainty is a constraint violation.

---

## 13. Compliance and Privacy Constraints

## 13.1 Minimize Sensitive Exposure

Only the minimum necessary sensitive information should be collected, stored, or exposed.

The system should not gather data “just in case.”

---

## 13.2 Privacy-Aware Defaults

Protected data views should default to the minimum necessary exposure.
Admin visibility should still remain bounded and intentional.

---

## 13.3 Future Compliance Expansion Must Be Explicit

If requirements later include GDPR, CCPA, PCI, or other regulatory obligations, those obligations must be added explicitly through specs and decisions.

The MVP must not assume compliance by implication.

---

## 14. Non-Negotiable Forbidden Patterns

The following patterns are explicitly forbidden in the MVP:

- committing secrets,
- bypassing authentication or authorization,
- using AI as unreviewed runtime decision-maker for core logic,
- skipping tests for critical logic,
- silent schema or architecture drift,
- building large features without specs,
- hiding failures,
- storing core business truth in ad hoc files or assistant memory,
- allowing destructive behavior without review,
- expanding scope without approval.

Any occurrence of these patterns requires immediate correction.

---

## 15. Constraint Enforcement Rule

If a proposed implementation conflicts with:
- this constraints file,
- the requirements file,
- acceptance criteria,
- relevant ADRs,

the implementation must be revised before it is accepted.

A working shortcut that violates constraints is still a failed implementation.

---

## 16. Open Questions

- What retention period should apply to price observations in the first MVP?
- Which audit events are mandatory versus optional for the first release?
- What exact approval threshold should trigger a “risky change” review in future workflow specs?
- Which protected reports should manager role access by default in the MVP?