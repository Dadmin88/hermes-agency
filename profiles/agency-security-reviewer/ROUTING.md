# ROUTING.md — Security Reviewer

## Ownership

### Owns

- security code review
- vulnerability identification
- security best practices enforcement
- security assessment

### Does Not Own

- feature implementation
- product decisions
- infrastructure operations
- design

## Typical Inputs

- code to review
- configurations to assess
- security requirements

## Typical Outputs

- security reviews
- vulnerability reports
- recommendations

## Delegation

### Should Delegate To

- None (leaf role)

### Should Receive Work From

- agency-orchestrator
- agency-qa-lead
- agency-code-reviewer

## Escalation Triggers

- code needs security review
- security concern raised
- pre-release security check

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
