---
name: sop-writing
description: Write clear, executable Standard Operating Procedures for repeatable processes
tags: [operations, sop, documentation, process, procedures, standardization]
---

# SOP Writing

## When to Use
When documenting a repeatable process that needs to be executed consistently by different people or agents. This applies to deployment procedures, incident response, onboarding checklists, maintenance routines, approval workflows, and any process where consistency and reliability matter.

## Prerequisites
- Understanding of the process being documented (or access to someone who does)
- Knowledge of who will execute the SOP and their skill level
- Access to any tools, systems, or resources referenced in the procedure

## Steps

### Step 1: Define Scope and Purpose
Before writing steps, clarify what this SOP covers and why it exists.

**SOP header template:**
```markdown
# SOP: [Process Name]

**Purpose:** [One sentence: why this SOP exists]
**Scope:** [What this SOP covers and what it does NOT cover]
**Owner:** [Role/team responsible for maintaining this SOP]
**Last Updated:** [Date]
**Review Cycle:** [How often this SOP should be reviewed — e.g., quarterly]

## Applicability
- **Who should use this:** [Roles]
- **When to use this:** [Triggers/situations]
- **Prerequisites:** [What must be true before starting]
```

**Example:**
```markdown
# SOP: Production Database Migration

**Purpose:** Ensure database schema changes are applied safely to production 
with zero data loss and minimal downtime.
**Scope:** Covers PostgreSQL schema migrations. Does NOT cover data backfills 
or application deployments.
**Owner:** Database Engineering team
**Last Updated:** 2024-01-15
**Review Cycle:** Quarterly
```

### Step 2: List Prerequisites and Resources
Document everything needed before the procedure can begin.

```markdown
## Prerequisites

### Required Access
- [ ] Production database credentials (stored in Vault at secret/db/prod)
- [ ] SSH access to database server (db-prod-01.internal)
- [ ] GitHub write access to the repository

### Required Tools
- [ ] psql client (version 14+)
- [ ] Database migration tool (Flyway/Liquibase/Alembic)
- [ ] VPN connection to production network

### Required Approvals
- [ ] Migration plan reviewed by DBA
- [ ] Change request approved in ServiceNow (CR-XXXX)
- [ ] Maintenance window scheduled and communicated

### Timing
- Execute during maintenance window: [Day] [Time] [Timezone]
- Estimated duration: 30-60 minutes
- Rollback window: Must be completable within 30 minutes
```

### Step 3: Write the Procedure Steps
Each step must be specific, sequential, and verifiable.

**Step writing rules:**
1. One action per step (not "do X and Y")
2. Start with a verb: "Run...", "Check...", "Verify...", "Copy..."
3. Include the exact command, path, or URL
4. Include expected output or result
5. Note decision points clearly

```markdown
## Procedure

### Step 1: Verify preconditions
Run the pre-migration checklist to ensure the system is ready.

```bash
# Check database connectivity
psql -h db-prod-01.internal -U deploy -d myapp -c "SELECT 1;"
# Expected output: returns 1 row with value 1

# Check current migration version
psql -h db-prod-01.internal -U deploy -d myapp -c "SELECT version FROM schema_version ORDER BY installed_on DESC LIMIT 1;"
# Record this version number for rollback

# Verify backup exists and is recent
ls -la /backups/db/myapp/latest.sql.gz
# Must be less than 4 hours old
```

✅ **Checkpoint:** All three checks pass. If any fail, STOP and contact the DBA.

### Step 2: Create a fresh backup
```bash
pg_dump -h db-prod-01.internal -U deploy -d myapp | gzip > /backups/db/myapp/pre-migration-$(date +%Y%m%d-%H%M%S).sql.gz
```

✅ **Checkpoint:** Backup file exists and is non-empty.

### Step 3: Apply the migration
```bash
cd /opt/myapp
alembic upgrade head
```

Expected output: "Running upgrade X -> Y" for each pending migration.

✅ **Checkpoint:** Migration completes without errors. If errors occur, proceed to Rollback.

### Step 4: Verify the migration
```bash
# Check new schema version
psql -h db-prod-01.internal -U deploy -d myapp -c "SELECT version FROM schema_version ORDER BY installed_on DESC LIMIT 1;"
# Should show the new version

# Verify new columns/tables exist
psql -h db-prod-01.internal -U deploy -d myapp -c "\d+ table_name"
# Should show new columns

# Run application smoke test
curl -s https://api.myapp.com/health | jq .
# Should return {"status": "ok"}
```

✅ **Checkpoint:** Schema is at expected version, tables match specification, health check passes.
```

### Step 4: Document Rollback Procedure
Every SOP that makes changes must include how to undo those changes.

```markdown
## Rollback Procedure

**Trigger:** Roll back if any step fails or if verification shows issues.

### Rollback Step 1: Restore from backup
```bash
# Stop application connections
psql -h db-prod-01.internal -U deploy -d myapp -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'myapp' AND pid <> pg_backend_pid();"

# Restore from pre-migration backup
gunzip < /backups/db/myapp/pre-migration-YYYYMMDD-HHMMSS.sql.gz | psql -h db-prod-01.internal -U deploy -d myapp
```

### Rollback Step 2: Verify restoration
```bash
psql -h db-prod-01.internal -U deploy -d myapp -c "SELECT version FROM schema_version ORDER BY installed_on DESC LIMIT 1;"
# Should show the previous version number
```

### Rollback Step 3: Notify stakeholders
Send notification to #engineering-alerts:
> "Database migration rolled back. Reason: [describe]. System restored to previous state."
```

### Step 5: Add Communication and Escalation Paths
Define who to contact and when.

```markdown
## Communication Plan

| Event | Notify | Channel | When |
|-------|--------|---------|------|
| Migration starting | Engineering team | #engineering | Before Step 1 |
| Migration complete | Engineering team | #engineering | After Step 4 |
| Migration failed | On-call DBA + Eng Lead | #incidents + phone | Immediately |
| Rollback initiated | VP Engineering + Product | #incidents + email | Within 5 min |

## Escalation
1. **Level 1:** On-call engineer (handles standard issues)
2. **Level 2:** DBA team (handles database-specific issues)
3. **Level 3:** VP Engineering (handles business impact decisions)
```

### Step 6: Review and Maintain
SOPs are living documents.

```markdown
## Review Log

| Date | Reviewer | Changes |
|------|----------|---------|
| 2024-01-15 | J. Smith | Initial creation |
| 2024-03-01 | A. Jones | Updated backup path |
| 2024-06-01 | J. Smith | Added Step 5 for connection draining |

## Review Checklist (Quarterly)
- [ ] All commands still work with current tool versions
- [ ] All URLs and paths are still valid
- [ ] Contact information is current
- [ ] Prerequisites still accurate
- [ ] No steps have been skipped in recent executions
```

## Tool Usage
- **file write**: Create the SOP document in the project's docs or operations folder
- **file read**: Review existing SOPs for format consistency, and system configs for accurate details
- **search_files**: Find related procedures, configuration files, and existing documentation
- **terminal**: Test commands in the SOP to verify they work as documented

## Pitfalls
1. **Don't assume knowledge** — write for someone who has never done this before
2. **Don't skip verification steps** — every step should have a way to confirm it worked
3. **Don't forget rollback** — if the SOP changes something, it must explain how to undo it
4. **Don't write vague steps** — "deploy the application" is not a step; "run `./deploy.sh prod`" is
5. **Don't let SOPs go stale** — review quarterly and after every incident
6. **Don't hide SOPs** — they should be findable (linked from README, wiki, or team docs)

## Verification
- A person unfamiliar with the process can follow the SOP from start to finish
- Every command in the SOP runs successfully when tested
- Rollback procedure is complete and tested
- Communication plan covers success, failure, and escalation
- All prerequisites are accurate and current

## Quick Reference
```
SOP STRUCTURE:
  Header (purpose, scope, owner, review cycle)
  Prerequisites (access, tools, approvals, timing)
  Procedure (steps with commands + checkpoints)
  Rollback (how to undo)
  Communication (who to notify, when)
  Review Log (who changed what, when)

STEP FORMAT: [Verb] + [Action] + [Expected Result]
ONE action per step. Checkpoint after each critical step.
```
