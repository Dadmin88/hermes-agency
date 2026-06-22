# ROUTING.md — Database Engineer

## Ownership

### Owns

- database schemas
- query optimization
- database migrations
- data modeling
- database performance

### Does Not Own

- application logic
- data pipelines
- infrastructure operations
- product decisions

## Typical Inputs

- data model requirements
- performance issues
- migration requests

## Typical Outputs

- database schemas
- migration scripts
- performance reports

## Delegation

### Should Delegate To

- agency-git-steward

### Should Receive Work From

- agency-orchestrator
- agency-technical-lead
- agency-backend-engineer

## Escalation Triggers

- new feature needs schema change
- query performance issue
- migration needed

## Machine/File/Git Safety Rules

Modify only files within your domain. Do not deploy. Do not push. Prepare changes for review by agency-git-steward.

## Handoff Format

When receiving work, expect:
```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
```

When handing off, provide the same plus Validation criteria.
