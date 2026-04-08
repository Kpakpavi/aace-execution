# AACE MVP Breakdown Plan

## 1. Purpose

This document defines the implementation decomposition for the AACE MVP.

Its purpose is to break the MVP into small, reviewable, dependency-aware phases so that the system can be built intentionally and validated progressively.

This file does not describe every technical detail of implementation.
Instead, it defines:

- build order,
- dependency structure,
- phase goals,
- completion gates,
- risk-aware sequencing.

The breakdown plan exists to prevent uncontrolled build sprawl and to keep implementation aligned with requirements, constraints, and acceptance criteria.

---

## 2. Breakdown Philosophy

The AACE MVP must be built in layers.

The project should not begin by attempting to build everything at once.
It should proceed by establishing stable foundations first, then adding business capability on top of those foundations.

The decomposition must satisfy the following principles:

1. each phase must produce something understandable and reviewable,
2. each phase must reduce uncertainty rather than increase it,
3. each phase must preserve system safety and determinism,
4. later phases must depend on validated outputs from earlier phases,
5. no phase should assume unfinished behavior from later phases.

The build order must prefer:

- correctness over speed,
- stable interfaces over speculative flexibility,
- explicit boundaries over hidden coupling.

---

## 3. MVP Decomposition Strategy

The MVP is decomposed into eight major phases:

1. Foundation and Specification Lock
2. Auth and Access Control
3. Core Data Model and Persistence
4. Ingestion Pipeline
5. Price Monitoring and Discrepancy Detection
6. Opportunity Scoring and Review Surface
7. Reporting, Auditability, and Operational Visibility
8. End-to-End Hardening and Release Readiness

Each phase must complete its own success criteria before the next phase becomes implementation-active.

---

## 4. Phase 0 — Foundation and Specification Lock

## 4.1 Objective

Establish the non-code foundation that governs the build.

## 4.2 Scope

This phase includes:

- verifying `claude.md` is present and followed,
- defining ADRs,
- defining the core spec set,
- aligning the project to the modular monolith architecture,
- locking MVP boundaries,
- establishing the expected build order.

## 4.3 Deliverables

This phase should produce:

- ADR files for architecture, storage, and auth/access,
- overview, requirements, acceptance criteria, constraints, breakdown plan, and evaluation plan,
- initial feature-spec structure,
- confirmed implementation boundaries.

## 4.4 Exit Criteria

This phase is complete when:

- high-level system intent is documented,
- core constraints are documented,
- the MVP boundary is stable,
- major architectural ambiguity is removed,
- the team can explain what will be built and what will not be built.

## 4.5 Risks Addressed

This phase reduces:

- ambiguous implementation,
- hidden scope expansion,
- architecture drift,
- uncontrolled AI-assisted generation.

---

## 5. Phase 1 — Auth and Access Control

## 5.1 Objective

Establish secure access boundaries before exposing any protected functionality.

## 5.2 Scope

This phase includes:

- user authentication flow,
- role-based access control,
- protected route/API enforcement,
- basic user and role representation,
- authentication-related event logging.

## 5.3 Why This Phase Comes Early

Without auth and authorization:

- dashboards cannot be protected,
- administrative capabilities cannot be safely introduced,
- role-sensitive reporting cannot be validated,
- system trust is undermined.

This phase is intentionally placed before feature surfaces that expose business data.

## 5.4 Deliverables

This phase should produce:

- authenticated user access path,
- RBAC enforcement for admin, manager, and user,
- protected application/API surfaces,
- safe authentication failure handling,
- traceable auth events.

## 5.5 Exit Criteria

This phase is complete when:

- users can authenticate,
- unauthorized access is blocked,
- role restrictions are working,
- protected routes are testable,
- auth flows are covered by tests.

## 5.6 Risks Addressed

This phase reduces:

- accidental public exposure,
- uncontrolled admin access,
- unclear ownership of data and actions.

---

## 6. Phase 2 — Core Data Model and Persistence

## 6.1 Objective

Create the minimum durable data foundation required for the MVP.

## 6.2 Scope

This phase includes explicit support for:

- users,
- roles/access relationships,
- products,
- marketplace listings,
- price observations,
- opportunity evaluations,
- audit/event records.

## 6.3 Why This Phase Comes Before Business Logic

Business logic cannot be trusted if the system does not have a stable and queryable representation of core entities.
This phase ensures that later evaluation, reporting, and audit behavior are built on a defined system of record.

## 6.4 Deliverables

This phase should produce:

- the initial explicit data model,
- persistence paths for required domains,
- clear distinctions between persisted vs derived data,
- traceable relationships between products, listings, observations, and opportunities.

## 6.5 Exit Criteria

This phase is complete when:

- required core entities can be stored and retrieved,
- core relationships are valid and testable,
- data boundaries are understandable,
- audit/event records have an intentional model.

## 6.6 Risks Addressed

This phase reduces:

- schema drift,
- untraceable business state,
- weak reporting foundations,
- overreliance on flexible unstructured data.

---

## 7. Phase 3 — Ingestion Pipeline

## 7.1 Objective

Enable controlled intake of product and listing data.

## 7.2 Scope

This phase includes:

- approved input path(s),
- validation of required fields,
- normalization into internal representations,
- source-context retention,
- failure handling for malformed inputs.

## 7.3 Why This Phase Comes Before Monitoring

Discrepancy detection is only as good as the quality of the ingested data.
The system must prove it can accept, validate, and normalize inputs before it attempts to evaluate them.

## 7.4 Deliverables

This phase should produce:

- one complete ingestion path,
- predictable invalid-input handling,
- normalized product/listing creation or update behavior,
- traceability from ingested source to stored records.

## 7.5 Exit Criteria

This phase is complete when:

- valid inputs can be ingested end-to-end,
- invalid inputs are rejected or flagged safely,
- normalized records are stored correctly,
- ingestion events are traceable.

## 7.6 Risks Addressed

This phase reduces:

- garbage-in / garbage-out evaluation,
- silent input corruption,
- hidden ingestion failures.

---

## 8. Phase 4 — Price Monitoring and Discrepancy Detection

## 8.1 Objective

Implement the core value engine of the MVP: controlled price comparison and discrepancy detection.

## 8.2 Scope

This phase includes:

- comparison of pricing data across defined sources,
- explicit discrepancy rules,
- thresholding of meaningful vs insignificant differences,
- repeatable detection behavior,
- explainable evaluation outputs.

## 8.3 Why This Phase Is Central

This phase is the heart of the product promise.
If this phase is weak, the MVP may have data and access controls but no useful business signal.

## 8.4 Deliverables

This phase should produce:

- discrepancy evaluation logic,
- deterministic rule execution,
- explainable discrepancy outputs,
- test coverage for comparison behavior.

## 8.5 Exit Criteria

This phase is complete when:

- discrepancies can be detected reliably,
- the same inputs produce the same results,
- rule behavior is test-covered,
- detected discrepancies can be explained plainly.

## 8.6 Risks Addressed

This phase reduces:

- noisy signal generation,
- false opportunity surfacing,
- unexplainable system outputs.

---

## 9. Phase 5 — Opportunity Scoring and Review Surface

## 9.1 Objective

Transform raw discrepancies into prioritized opportunity outputs visible to authorized users.

## 9.2 Scope

This phase includes:

- deterministic opportunity scoring,
- preservation of score factors,
- ranking or prioritization,
- protected output access,
- structured API or dashboard review surface.

## 9.3 Why This Phase Follows Detection

The system must first prove it can detect discrepancies before it can rank them meaningfully.
Scoring without trustworthy detection would amplify noise rather than value.

## 9.4 Deliverables

This phase should produce:

- opportunity generation from discrepancies,
- transparent score computation,
- authorized user review flow,
- clear representation of score and supporting factors.

## 9.5 Exit Criteria

This phase is complete when:

- opportunities are generated from valid discrepancies,
- scores are deterministic and explainable,
- authorized users can review outputs,
- protected output views are working,
- score logic is independently testable.

## 9.6 Risks Addressed

This phase reduces:

- black-box prioritization,
- inaccessible outputs,
- unreviewable scoring behavior.

---

## 10. Phase 6 — Reporting, Auditability, and Operational Visibility

## 10.1 Objective

Provide enough visibility to support trust, debugging, and early operational use.

## 10.2 Scope

This phase includes:

- basic reporting outputs,
- opportunity counts and summaries,
- recent activity views,
- audit/event record visibility,
- operational traceability for critical flows.

## 10.3 Why This Phase Matters

An MVP without visibility may appear to work but remain impossible to trust or maintain.
This phase proves that outputs and system actions can be reviewed after the fact.

## 10.4 Deliverables

This phase should produce:

- basic reporting views or endpoints,
- audit/event inspection capability,
- traceability of ingestion, evaluation, and access activity,
- support for debugging and review.

## 10.5 Exit Criteria

This phase is complete when:

- authorized reporting access works,
- counts and summaries are consistent with stored data,
- critical system actions are traceable,
- audit logs are useful and safely bounded.

## 10.6 Risks Addressed

This phase reduces:

- invisible failures,
- weak accountability,
- inability to explain past system behavior.

---

## 11. Phase 7 — End-to-End Hardening and Release Readiness

## 11.1 Objective

Validate the system as a coherent MVP rather than a set of individually working parts.

## 11.2 Scope

This phase includes:

- end-to-end flow validation,
- happy-path confirmation,
- edge-case testing,
- failure-path validation,
- retry-path validation where applicable,
- documentation tightening,
- known-risk review.

## 11.3 Why This Phase Is Final

A system should not be called MVP-ready merely because subsystems exist.
The full product loop must work together under defined tests.

## 11.4 Deliverables

This phase should produce:

- passing end-to-end validation for the core scenario,
- test evidence for critical flows,
- known limitations documented,
- readiness assessment against acceptance criteria.

## 11.5 Exit Criteria

This phase is complete when:

- the minimum end-to-end scenario passes,
- critical acceptance criteria are satisfied,
- known risks are documented,
- the MVP can be explained, tested, and reviewed as a complete system.

## 11.6 Risks Addressed

This phase reduces:

- false completion claims,
- brittle integration boundaries,
- unverified cross-domain assumptions.

---

## 12. Cross-Phase Dependency Rules

The following dependency rules apply:

1. auth-dependent review surfaces must not be treated as complete before auth works,
2. scoring must not be finalized before discrepancy detection exists,
3. discrepancy detection must not be trusted before ingestion is reliable,
4. reporting must not precede stable persisted data and event capture,
5. end-to-end testing must not replace phase-level validation.

Each phase depends on validated foundations from earlier phases.

---

## 13. Work Unit Guidance

Each phase should be broken into small implementation units.

A valid work unit should:

- have one clear purpose,
- stay within one primary domain boundary,
- be reviewable,
- be testable,
- avoid broad collateral edits.

Examples of valid work units include:

- add RBAC enforcement to protected route layer,
- add product ingestion validation,
- add deterministic discrepancy comparison function,
- add opportunity score explanation fields,
- add audit logging for evaluation events.

Examples of invalid work units include:

- “build the whole dashboard,”
- “set up everything for auth and APIs,”
- “make the whole system production-ready.”

---

## 14. Phase Review Gates

Before a phase is considered complete, it must pass a review gate.

Each review gate should confirm:

1. the phase objective was achieved,
2. implementation matches relevant specs,
3. acceptance criteria for that phase are met,
4. tests exist for critical behavior,
5. no constraint violations were introduced,
6. known limitations are documented.

A phase without a passed review gate should not be treated as stable foundation for the next phase.

---

## 15. Change Control During Breakdown Execution

If a later phase reveals that an earlier phase was underspecified or incorrectly scoped:

- the issue must be documented,
- the relevant spec or ADR must be updated,
- the phase plan may be revised deliberately,
- implementation should not quietly drift.

The correct behavior is controlled revision, not silent adaptation.

---

## 16. Success Condition for the Breakdown Plan

This breakdown plan is successful if it enables a contributor to:

- understand the correct build order,
- avoid premature implementation,
- work in small, intentional steps,
- validate progress phase by phase,
- reach a tested MVP without uncontrolled scope expansion.

---

## 17. Open Questions

- Should the first user-facing review surface be dashboard-first or API-first?
- Which ingestion path should be the very first implementation slice?
- What minimum dataset is needed to validate the discrepancy engine well?
- Which reporting outputs are required in the first release versus immediately after MVP?