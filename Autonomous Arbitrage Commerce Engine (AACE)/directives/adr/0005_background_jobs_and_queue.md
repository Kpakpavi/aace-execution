# ADR 0005: Background Jobs and Queue

## Status
Proposed

## Context
- AACE requires background processing for tasks that should not block user-facing requests.
- Key background workloads include:
  - scheduled price data fetching from marketplace adapters,
  - discrepancy detection runs,
  - opportunity scoring evaluation,
  - alert generation.
- These workloads must be:
  - reliable under restart,
  - idempotent where retries are possible,
  - observable and traceable,
  - safe under concurrent execution.
- The background job model affects system complexity, operational safety, and scalability.

## Decision
- Choose ONE approach for the MVP:
  - Simple scheduled job runner using the host application scheduler or a lightweight cron-compatible mechanism.
- For the MVP, a queue-based message broker is NOT required unless justified by a specific retry or concurrency requirement.
- Each job must:
  - have a single, clearly defined responsibility,
  - be idempotent,
  - log its start, completion, and any errors,
  - be testable in isolation without requiring the full application stack.
- Jobs must call execution layer scripts directly and must not contain orchestration logic.

## Alternatives Considered
- Full message queue with broker (e.g., Redis, RabbitMQ, Celery): deferred to post-MVP
- Serverless function triggers: deferred unless deployment model requires it
- Manual job execution only: acceptable for development, not for production MVP
- In-request background threading: rejected due to reliability and observability concerns

## Consequences

### Positive
- Simple to implement and operate for MVP
- Easy to test and trace
- Lower infrastructure dependency
- Clear execution boundaries

### Negative
- Less resilient than a full queue under high load or partial failure
- No built-in retry queue without explicit implementation
- May require migration to a proper queue as workloads grow

## Job Design Rules
- Each job must have exactly one clear responsibility
- Jobs must be safe to rerun without creating duplicate side effects
- Jobs must log start time, end time, and outcome
- Failed jobs must surface as explicit exceptions
- No job may assume it is the only instance running unless explicitly designed for single execution

## Retry Policy
- Define the default maximum retry count for transient failures
- Define which error types are retriable versus terminal
- Retried jobs must not duplicate durable actions such as duplicate alerts or opportunity records

## Scheduling Rules
- Job schedules must be defined in configuration, not hardcoded in logic
- Schedules must be visible and reviewable
- Frequency decisions must be documented in the relevant directive

## Implications for AACE
- Explain impact on:
  - /execution job structure
  - /services/worker scheduling responsibility
  - /config job schedule definitions
  - test requirements for job isolation and idempotency
  - observability requirements for job tracing

## Open Questions
- What is the minimum acceptable retry behavior for MVP?
- Should job results be persisted to the database or only logged?
- Which jobs are strictly periodic versus event-triggered?
- At what point should a message queue replace the simple scheduler?
