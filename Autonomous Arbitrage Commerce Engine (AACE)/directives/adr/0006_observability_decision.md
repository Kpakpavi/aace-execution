# ADR 0006: Observability Decision

## Status
Proposed

## Context
- AACE must be observable to be trustworthy.
- Operators, developers, and Claude itself need to understand what the system is doing, what has failed, and why.
- The observability strategy affects:
  - debuggability during development,
  - production incident detection,
  - audit trail completeness,
  - complexity of the system.
- The MVP should not require expensive third-party monitoring platforms.
- Observability must support the Self-Annealing Loop defined in CLAUDE.md.

## Decision
- Choose ONE observability approach for the MVP:
  - Structured application logging as the primary observability mechanism.
- Logs must be:
  - structured (e.g., JSON or consistent key-value format),
  - timestamped,
  - categorized by event type,
  - written to stdout/stderr or a configurable output target.
- No external observability platform is required for the MVP.
- Basic metrics (counts, error rates) may be implemented as simple application-level counters, not full metrics pipelines.
- Distributed tracing is deferred to post-MVP.

## Alternatives Considered
- Full external observability stack (e.g., Datadog, Sentry, Prometheus): deferred to post-MVP
- Unstructured log strings: rejected due to limited debuggability
- Database-only audit logs without application logs: insufficient for debugging
- No observability plan: rejected, violates CLAUDE.md requirements

## Consequences

### Positive
- Low infrastructure overhead for MVP
- Structured logs are immediately useful for debugging
- Easy to extend to external platforms later
- Aligns with audit log requirements in the spec

### Negative
- Manual log review required without dashboards
- No alerting pipeline in MVP
- Metrics visibility limited without dedicated tooling

## Logging Requirements
- All critical system events must be logged
- Logs must never include: passwords, secrets, tokens, raw credentials, sensitive PII
- Log levels must be used consistently:
  - INFO for normal operations
  - WARN for recoverable unexpected states
  - ERROR for failures requiring attention
- Log output must be environment-configurable

## Audit Log Alignment
- Observability logs must align with the audit/event model defined in the data model
- Key user and system actions must appear in both structured logs and the audit event store
- Duplicate logging of the same event is acceptable but must be intentional

## Failure Visibility Rules
- The system must never fail silently
- All critical failures must produce a log entry
- Error logs must include enough context to identify the failing component and its inputs

## Post-MVP Observability Path
- When the MVP is stable, consider:
  - external error tracking,
  - a metrics pipeline,
  - distributed tracing for multi-service deployments.

## Implications for AACE
- Explain impact on:
  - /execution logging conventions
  - /services/worker event logging
  - /config log level and output configuration
  - test requirements for log output validation
  - audit trail completeness requirements

## Open Questions
- Should log output format be enforced by a shared logger utility?
- What minimum log retention period is acceptable for MVP?
- Which system events are mandatory audit events versus optional debug logs?
- When does observability complexity justify adding an external platform?
