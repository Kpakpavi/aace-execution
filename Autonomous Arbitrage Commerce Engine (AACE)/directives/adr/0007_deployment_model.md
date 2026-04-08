# ADR 0007: Deployment Model

## Status
Proposed

## Context
- AACE must be deployable in a way that is:
  - safe to run in production,
  - reproducible across environments,
  - understandable by a junior developer,
  - consistent with the modular monolith architecture defined in ADR 0001.
- The deployment model affects:
  - environment separation (dev, staging, production),
  - secret and configuration management,
  - availability and restart behavior,
  - operational overhead for the MVP.
- The MVP should prefer simplicity over infrastructure complexity.

## Decision
- Choose ONE deployment model for the MVP:
  - Containerized application (Docker) deployed to a single-instance managed hosting environment.
- The MVP does not require:
  - multi-region deployment,
  - auto-scaling,
  - Kubernetes or container orchestration,
  - complex CI/CD pipelines beyond basic deployment automation.
- Environments must be separated:
  - development (local),
  - production (or production-like staging).
- Configuration must be injected via environment variables, not hardcoded.
- Secrets must never be stored in the repository.

## Alternatives Considered
- Bare-metal or VM-only deployment without containers: rejected due to reproducibility concerns
- Serverless function deployment: deferred unless adapter workloads clearly justify it
- Kubernetes: deferred to post-MVP
- Platform-as-a-Service without Docker: acceptable fallback if Docker adds unnecessary friction for MVP

## Consequences

### Positive
- Reproducible environments via containerization
- Simpler dependency management
- Clear boundary between application and infrastructure
- Easy to run locally with Docker Compose

### Negative
- Adds container build and run complexity
- Requires container registry for deployment artifacts
- Restart and health check behavior must be explicitly defined

## Environment Rules
- Each environment must have its own configuration values
- No environment should share secrets with another
- Production writes must require explicit environment verification in execution scripts
- The application must detect its environment via a configuration flag or environment variable

## Secret Management Rules
- All secrets must be injected at runtime via environment variables
- No secret values may be committed to version control
- Secret rotation procedures should be documented in /docs
- The application must fail fast and clearly if required secrets are missing at startup

## Health and Restart Rules
- The application must expose a basic health check endpoint
- Health checks must not expose internal system state or secrets
- The application must restart safely without requiring manual data cleanup
- Background jobs must resume safely after restart

## Deployment Process
- Define the expected steps to deploy a new version
- Deployments must not require manual database modifications unless a migration script is provided and tested
- Rollback procedure must be defined for production deployments

## Implications for AACE
- Explain impact on:
  - /config environment wiring
  - Docker and Docker Compose setup
  - CI pipeline requirements
  - /docs setup and deployment instructions
  - secret injection model
  - intern safety requirements from CLAUDE.md

## Open Questions
- Which managed hosting provider is preferred for the first production deployment?
- Should Docker Compose be the local development standard?
- Is a staging environment required before the first production release?
- What is the rollback plan if a production deployment fails?
