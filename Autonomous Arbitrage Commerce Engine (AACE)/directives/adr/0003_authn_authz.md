# ADR 0003: Authentication and Authorization

## Status
Proposed

## Context
- Describe the AACE MVP need for:
  - secure user login
  - account ownership
  - protected dashboards and APIs
  - future marketplace credential handling
  - internal/admin access boundaries
- Explain why auth and access control affect safety, auditability, and compliance.
- State that the MVP should prefer a simple, well-understood model over a highly customized auth system.

## Decision
- Choose ONE MVP approach:
  - Email/password authentication with secure password hashing and session-based or token-based authenticated API access
- Choose ONE MVP authorization model:
  - Role-based access control (RBAC) with at least:
    - admin
    - manager
    - user
- Justify both choices clearly.
- State that marketplace credentials, if added later, must be stored separately and securely, and are not required for the first MVP unless explicitly approved.

## Alternatives Considered
- Magic-link only authentication
- OAuth-only authentication
- Attribute-based access control (ABAC)
- Custom policy engine from day one
- No roles in MVP

## Consequences

### Positive
- Clear and teachable access model
- Easier route and API protection
- Good auditability of user actions
- Lower implementation complexity for MVP

### Negative
- Less flexible than fine-grained policy systems
- May require migration if enterprise requirements grow
- Needs careful session/token expiration and reset flows

## MVP Access Model
- Define what each role can access at a high level:
  - admin
  - manager
  - user
- Clarify protected areas:
  - dashboard
  - reporting
  - user management
  - future integration settings
- State that least privilege is the default rule.

## Security Requirements
- Passwords must be hashed securely
- Secrets must never be stored in repo
- Authentication failures should be logged safely
- Account recovery/reset flows must avoid leaking sensitive information
- Rate limiting / lockout considerations should be acknowledged for future implementation

## Implications for AACE
- Explain impact on:
  - API contracts
  - data model
  - dashboard behavior
  - audit/event logs
  - future marketplace integrations
  - Claude orchestration boundaries

## Open Questions
- Should the MVP use sessions or JWTs for authenticated API access?
- What events must be retained for audit logs?
- When would SSO or OAuth become necessary?