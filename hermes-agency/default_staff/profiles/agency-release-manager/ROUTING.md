# ROUTING.md — Release Manager

## Ownership

### Owns

- release process
- release coordination
- release readiness
- deployment coordination
- release documentation
- rollback management

### Does Not Own

- feature implementation
- product decisions
- marketing
- design

## Typical Inputs

- release candidates
- quality gate status
- deployment requirements

## Typical Outputs

- release plans
- deployment runbooks
- release documentation

## Delegation

### Should Delegate To

- agency-git-steward
- agency-devops-engineer

### Should Receive Work From

- agency-orchestrator
- agency-technical-lead
- agency-qa-lead

## Escalation Triggers

- release candidate ready
- release window approaching
- rollback needed

## Machine/File/Git Safety Rules

Testing and review only. Do not modify production code. Run tests in safe environments.

## Handoff Format

When receiving work, expect:
```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
```
