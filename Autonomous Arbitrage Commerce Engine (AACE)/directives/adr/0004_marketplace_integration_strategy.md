# ADR 0004: Marketplace Integration Strategy

## Status
Proposed

## Context
- AACE depends on external marketplace data to detect price discrepancies.
- Marketplaces such as Amazon, eBay, and Shopify provide product and pricing data through APIs with varying rate limits, authentication models, and data formats.
- The integration strategy affects:
  - data freshness and reliability,
  - system safety under API failures,
  - implementation complexity,
  - cost and credential management.
- The MVP must prove the discrepancy detection model before committing to broad marketplace coverage.

## Decision
- Choose ONE integration approach for the MVP:
  - Adapter-based integration where each marketplace is wrapped in a dedicated, isolated adapter module.
- Each adapter must:
  - implement a common internal interface for fetching product and price data,
  - handle marketplace-specific authentication and rate limiting internally,
  - normalize output to a standard internal data model before handing off to the execution layer.
- The MVP should target a minimal set of marketplaces (one to two) to prove the integration model before expanding.

## Alternatives Considered
- Direct marketplace API calls embedded in core execution logic (rejected: creates tight coupling)
- Third-party unified marketplace aggregation service (rejected: premature dependency and cost)
- Flat file or CSV-based marketplace simulation only (acceptable for early dev, but not the production target)
- Full parallel multi-marketplace integration from day one (rejected: too broad for MVP)

## Consequences

### Positive
- Adapters are isolated and independently testable
- Marketplace-specific failures are contained
- Common interface enables consistent processing downstream
- New marketplaces can be added without changing core logic

### Negative
- Each adapter requires dedicated implementation and testing
- Authentication and rate limit behavior varies per marketplace
- Initial adapter design must be generalized enough to support future markets

## Integration Safety Rules
- Adapters must never write to marketplace accounts in the MVP
- All integration credentials must be stored outside the repository
- Rate limit handling must be built into each adapter
- Adapter failures must surface as explicit exceptions with clear error types
- Retries must be idempotent and bounded

## MVP Marketplace Priority
- Define which one or two marketplaces are included in the first MVP slice
- Remaining marketplaces should be treated as future integration work
- Adapter interfaces must be designed to accommodate additional markets without core changes

## Implications for AACE
- Explain impact on:
  - /execution adapter structure
  - /config credential management
  - data model for marketplace listings
  - testing and mock strategy for marketplace calls
  - Claude orchestration boundaries when integrations are involved

## Open Questions
- Which marketplace is included in the first functional slice?
- Should mock adapters be required for all MVP tests?
- What is the minimum data required from each marketplace adapter output?
- How should adapter failures be reported to the observability layer?
