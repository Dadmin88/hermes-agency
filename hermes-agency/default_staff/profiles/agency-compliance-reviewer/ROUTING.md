# ROUTING.md — Compliance Reviewer

## Ownership

### Owns

- compliance review
- license compliance
- regulatory compliance
- policy adherence
- compliance documentation

### Does Not Own

- feature implementation
- product decisions
- marketing
- design

## Typical Inputs

- code to review
- processes to assess
- compliance requirements

## Typical Outputs

- compliance reports
- license audits
- regulatory assessments

## Delegation

### Should Delegate To

- agency-legal-ops

### Should Receive Work From

- agency-orchestrator
- agency-qa-lead
- agency-security-reviewer

## Escalation Triggers

- new dependency added
- regulatory change
- compliance audit needed

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
