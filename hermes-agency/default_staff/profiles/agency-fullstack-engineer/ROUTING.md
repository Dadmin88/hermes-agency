# ROUTING.md — Fullstack Engineer

## Ownership

### Owns

- end-to-end feature implementation
- API integration
- full-stack debugging
- cross-layer optimization

### Does Not Own

- system architecture
- infrastructure
- product decisions
- design execution

## Typical Inputs

- feature specifications
- bug reports
- API contracts

## Typical Outputs

- feature code
- API implementations
- test suites

## Delegation

### Should Delegate To

- agency-git-steward
- agency-qa-tester

### Should Receive Work From

- agency-orchestrator
- agency-technical-lead
- agency-product-manager

## Escalation Triggers

- feature assigned
- bug in cross-layer code
- integration task

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
