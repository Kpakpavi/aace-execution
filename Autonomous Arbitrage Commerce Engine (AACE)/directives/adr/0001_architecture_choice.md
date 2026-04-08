# ADR 0001: Architecture Choice

## Status
Proposed

## Context
- Describe the AACE system at a high level
- Include key requirements:
  - real-time price monitoring
  - multi-marketplace data ingestion
  - AI-assisted orchestration (Claude)
  - deterministic execution layer
- Explain why architecture choice is critical

## Decision
- Choose ONE:
  - Modular Monolith (preferred for MVP)
- Clearly justify the choice
- Explain how it supports:
  - safety
  - determinism
  - auditability
  - incremental scaling

## Alternatives Considered
- Microservices (explain why NOT now)
- Fully serverless orchestration
- Monolith without modular boundaries

## Consequences

### Positive
- Faster MVP development
- Easier debugging
- Strong control over system behavior

### Negative
- Future scaling limitations
- Requires discipline to maintain modularity

## Implications for AACE
- Define how this impacts:
  - /services structure (future)
  - Claude orchestration boundaries
  - execution layer separation

## Open Questions
- What would trigger migration to microservices?
- What scale threshold requires re-architecture?