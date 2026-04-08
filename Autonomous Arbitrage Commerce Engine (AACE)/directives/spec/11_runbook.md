# AACE MVP Runbook

## 1. Purpose

This document defines operational procedures for running, maintaining, and recovering the AACE MVP.

It is the reference for:

- starting and stopping the system,
- verifying system health,
- handling common failure scenarios,
- performing safe deployments,
- executing manual recovery steps.

This runbook is designed to be followed by a developer or operator with no prior session context.

---

## 2. Runbook Principles

All procedures in this runbook must be:

- deterministic (same steps produce same outcome),
- safe to execute without production knowledge loss,
- executable by a junior developer,
- aligned with the constraints defined in CLAUDE.md and the spec.

---

## 3. System Startup

### Local Development

1. Copy `.env.example` to `.env` and populate required values.
2. Start the database using the defined local setup command.
3. Run database migrations.
4. Start the application server.
5. Verify the health check endpoint responds correctly.

### Production

1. Confirm environment variables are set in the hosting environment.
2. Deploy the latest container image.
3. Run pending database migrations.
4. Confirm the health check endpoint responds correctly.
5. Confirm background jobs are scheduled and running.

---

## 4. System Shutdown

### Graceful Shutdown

1. Stop background job scheduler.
2. Allow in-progress jobs to complete or time out safely.
3. Stop the application server.
4. Confirm no active connections remain.

### Emergency Shutdown

1. Stop the application process.
2. Record the time and reason in the incident log.
3. Investigate before restarting.

---

## 5. Health Check

The system exposes a health check endpoint.

### Expected Response
- Status: healthy
- All required dependencies reachable

### Failure Response
- Identify which dependency is failing
- Do not expose internal secrets or system internals in the health response

---

## 6. Database Migrations

Migrations must be run:

- after every deployment that includes schema changes,
- before the application server starts serving traffic.

### Rules
- Migrations must be reviewed before execution in production.
- Migrations must be reversible where possible.
- Never manually modify the database schema without a migration file.

---

## 7. Background Job Operations

### Starting Jobs
- Jobs start automatically with the application scheduler.
- Confirm job schedules match the definitions in /config.

### Verifying Job Execution
- Check application logs for job start and completion entries.
- Verify expected records were created or updated.

### Stopping a Specific Job
- Disable the job in configuration.
- Redeploy or restart the scheduler.

### Rerunning a Failed Job
- Confirm the failure cause is resolved.
- Trigger the job manually using the defined CLI or admin command.
- Confirm idempotency: the rerun must not duplicate records.

---

## 8. Ingestion Operations

### Manual Ingestion Trigger
1. Confirm input data is valid and available.
2. Run the ingestion script with the target data source.
3. Confirm records were created in the database.
4. Check logs for validation errors or failures.

### Ingestion Failure Recovery
1. Identify the failure from logs.
2. Fix the input or adapter configuration.
3. Rerun ingestion safely (idempotent).
4. Verify expected records now exist.

---

## 9. Common Failure Scenarios

### Application Fails to Start
- Check environment variables are correctly set.
- Check database connectivity.
- Check for recent migration errors.
- Review startup logs.

### Authentication Failing
- Confirm the auth configuration is correct.
- Check for expired or missing secrets.
- Review auth-related logs for error details.

### Background Job Not Running
- Confirm scheduler is running.
- Check job configuration in /config.
- Review job-specific logs.
- Confirm no lock or duplicate prevention is blocking execution.

### Opportunity Records Not Generating
- Confirm ingestion completed successfully.
- Confirm discrepancy detection ran.
- Confirm scoring ran after detection.
- Review logs for each step.

### Database Connection Failure
- Confirm the database is running.
- Confirm connection string environment variable is correctly set.
- Check for network or credential issues.

---

## 10. Log Access

Logs are available via:

- the application's standard output in local development,
- the hosting environment's log viewer in production.

### What to Look For
- ERROR level entries for failures
- Job start/end timestamps to verify execution
- Ingestion and scoring completion entries
- Authentication failures

---

## 11. Deployment Procedure

1. Review changes being deployed.
2. Confirm tests pass in CI.
3. Build and tag the container image.
4. Push image to registry.
5. Deploy to the target environment.
6. Run pending migrations.
7. Verify health check passes.
8. Confirm background jobs resume.
9. Spot-check key functionality.

---

## 12. Rollback Procedure

If a deployment fails:

1. Redeploy the previous known-good container image.
2. Run any required rollback migrations (if reversible).
3. Verify system health.
4. Document the incident and root cause.

---

## 13. Incident Response

When an incident occurs:

1. Identify the component and scope of failure.
2. Preserve relevant logs before taking action.
3. Stop further damage (shut down if necessary).
4. Identify root cause.
5. Fix the underlying issue.
6. Add or update tests to prevent recurrence.
7. Update the relevant directive with the learning.

This follows the Self-Annealing Loop defined in CLAUDE.md.

---

## 14. Secrets Rotation

When a secret must be rotated:

1. Generate a new secret value.
2. Update the value in the hosting environment's secret store.
3. Redeploy the application to pick up the new value.
4. Confirm the system operates correctly after rotation.
5. Revoke the old secret.

Never store secret values in this runbook or any committed file.

---

## 15. Open Questions

- What is the defined CI tool and deployment trigger?
- Where are production logs accessible in the hosting environment?
- Who is the on-call contact for production incidents?
- What is the defined SLA for background job failure detection?
