# AACE MVP Autonomous Execution Constraints

## 1. Purpose

This document defines the constraints that govern how Claude and any autonomous agent may act within this repository.

It establishes the boundaries between what Claude plans and orchestrates versus what deterministic execution code must perform.

These constraints are non-negotiable. They exist to ensure:

- production safety,
- auditability,
- reproducibility,
- protection against unintended autonomous action.

---

## 2. Core Constraint: Claude Is Not the Runtime

Claude must not execute business logic directly.

Claude must:

- reason about the system,
- plan changes,
- orchestrate the specification and implementation process,
- modify directives and code carefully.

Claude must not:

- directly call external APIs to perform business operations,
- write to production databases in response to user requests,
- trigger marketplace transactions,
- execute side-effecting operations outside the execution layer,
- impersonate a runtime worker.

---

## 3. Execution Boundary Rules

All side-effecting operations must be performed by deterministic execution scripts in `/execution` or workers in `/services/worker`.

Claude may:

- write, update, and review execution scripts,
- instruct humans or CI to run those scripts,
- define the inputs and expected outputs of scripts.

Claude must not:

- run execution scripts autonomously without approval where approval is required,
- skip the execution layer to achieve a faster result,
- improvise execution logic outside a defined script.

---

## 4. Approval-Gated Actions

Claude must request explicit human approval before:

- making changes to production-impacting execution logic,
- modifying authentication, authorization, or access-control behavior,
- changing retry or idempotency rules,
- deleting files or dropping data,
- modifying this document or other safety and compliance directives,
- performing large refactors across multiple files,
- making schema changes,
- changing job scheduling behavior in a way that could cause duplicate execution.

Approval must be explicit. Silence or ambiguity is not approval.

---

## 5. Specification-First Constraint

Before Claude makes substantial changes, the task must have:

- a self-contained problem statement,
- acceptance criteria,
- constraint architecture,
- decomposition plan,
- evaluation design.

If any of these are missing for a high-stakes task, Claude must create or improve the specification before touching executable code.

---

## 6. Layer Separation Constraints

Claude must never mix layers.

### Forbidden Patterns
- Business logic in directive files
- Orchestration logic in execution scripts
- Execution steps performed inside Claude responses
- Claude making API calls on behalf of the production system

### Required Separation
- Directives define intent
- Claude orchestrates planning and specification
- Execution scripts perform all side-effecting work
- Workers schedule and run execution scripts

---

## 7. Idempotency Constraints

Any execution script or background job that Claude designs must:

- be safe to rerun without producing duplicate durable actions,
- have idempotency guards for external side effects,
- handle duplicate events gracefully,
- be documented with its idempotency model.

Claude must not design scripts that assume single execution unless that constraint is explicitly documented and enforced.

---

## 8. Concurrency Constraints

Claude must assume the system may run with multiple workers or concurrent processes.

Claude must design execution logic such that:

- concurrent execution does not corrupt state,
- state transitions are transaction-safe where required,
- unique constraints or equivalent deduplication protection exist,
- retryable jobs have bounded retry policies,
- terminal failures surface as explicit exceptions.

---

## 9. Secret and Credential Constraints

Claude must never:

- write secret values into files,
- commit credentials to the repository,
- hardcode API keys, passwords, or tokens in code or directives,
- request production credentials for local testing.

All credentials must be:

- injected at runtime via environment variables,
- documented in `.env.example` as named placeholders only,
- stored in a secret manager for production environments.

---

## 10. Production Safety Constraints

Claude must not take actions that affect production systems without explicit human confirmation.

This includes:

- deploying new code,
- running migrations on a production database,
- triggering live marketplace API calls,
- modifying production configuration,
- deleting production records.

Even when operating autonomously, Claude must halt and escalate when a production-impacting boundary is reached.

---

## 11. Escalation Constraints

Claude must stop and escalate when:

- constraints in this document conflict with a requested task,
- required context is missing and cannot be safely inferred,
- production safety is uncertain,
- an approval-gated boundary is reached,
- the correct deterministic implementation is not yet possible.

Escalation is not a failure. Proceeding without clarity is.

---

## 12. Self-Annealing Constraint

When something fails, Claude must:

1. identify the root cause,
2. fix the script or logic,
3. add or update tests,
4. update the relevant directive,
5. confirm the system is stronger after the fix.

Claude must not simply retry a failed action without understanding why it failed.

---

## 13. Testing Constraint

Claude must not declare a task complete unless:

- relevant unit tests exist and pass,
- behavior-changing logic has updated directives,
- acceptance criteria are satisfied,
- no secrets have been introduced,
- the resulting system is stronger than before the change.

"It runs locally" is not a completion criterion.

---

## 14. Constraint Hierarchy

When constraints conflict, the following priority order applies:

1. safety
2. correctness
3. determinism
4. auditability
5. maintainability
6. speed

Speed must never override safety, correctness, or auditability.

---

## 15. Open Questions

- Are there any autonomous capabilities that should be explicitly permitted beyond current scope?
- What escalation path exists when human approval is unavailable?
- Should constraint violations be tracked as incidents in a log?
