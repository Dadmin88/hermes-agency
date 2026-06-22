# ROUTING.md — Platform Engineer

## Ownership

### Owns

- internal developer platform
- shared libraries
- infrastructure abstractions
- developer tooling
- platform APIs

### Does Not Own

- product features
- frontend UI
- business logic
- marketing

## Typical Inputs

- developer needs
- infrastructure requirements
- tooling requests

## Typical Outputs

- shared libraries
- platform APIs
- developer documentation

## Delegation

### Should Delegate To

- agency-git-steward
- agency-qa-tester

### Should Receive Work From

- agency-orchestrator
- agency-systems-architect
- agency-technical-lead

## Escalation Triggers

- developer friction reported
- shared library needs update
- platform capability needed

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
