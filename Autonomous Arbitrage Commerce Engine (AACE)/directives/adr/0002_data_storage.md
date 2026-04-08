# ADR 0002: Data Storage

## Status
Proposed

## Context
- Describe the AACE MVP need to store:
  - users
  - product records
  - marketplace listings
  - price observations over time
  - opportunity evaluations
  - audit/event records
- Explain why storage choice affects determinism, auditability, and future analytics.
- Note that the MVP should prefer operational simplicity over premature scale.

## Decision
- Choose ONE:
  - PostgreSQL as the primary system of record
- Justify the choice clearly.
- State that structured relational data is the default.
- Allow JSONB only for bounded, explainable metadata or agent-output traces that do not replace core relational fields.

## Alternatives Considered
- NoSQL document database
- Event-store-first architecture
- Spreadsheet/manual-file-based storage
- Separate databases per service

## Consequences

### Positive
- Strong transactional consistency
- Clear schema evolution path
- Good support for analytics and audit queries
- Simpler MVP operations

### Negative
- Requires schema discipline
- Some highly variable data may need careful modeling
- Future scale patterns may require read replicas, partitioning, or specialized stores

## Data Boundaries for MVP
- Define the minimum entities the MVP should persist
- Distinguish required persisted data from derived/recomputable data
- Clarify that raw scraped or fetched source payloads should be stored selectively, not blindly

## Implications for AACE
- Explain impact on:
  - future /services modules
  - API contracts
  - reporting
  - evaluation and replayability
  - Claude orchestration boundaries

## Open Questions
- What retention policy should price history use?
- Which data should be immutable for audit purposes?
- What future needs would justify adding Redis, a warehouse, or object storage?