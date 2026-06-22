# ROUTING.md — Integration Engineer

## Ownership

### Owns

- external integrations
- API client implementations
- webhook handling
- third-party service connections
- integration testing

### Does Not Own

- internal architecture
- product decisions
- infrastructure operations
- marketing

## Typical Inputs

- integration requirements
- API documentation
- service specifications

## Typical Outputs

- integration code
- API clients
- webhook handlers
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

- new service integration needed
- integration failure
- API version change

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
