# ROUTING.md — Code Reviewer

## Ownership

### Owns

- code review quality
- coding standards enforcement
- review feedback
- code quality assessment

### Does Not Own

- feature implementation
- product decisions
- design
- infrastructure

## Typical Inputs

- pull requests
- code changes
- review requests

## Typical Outputs

- review feedback
- quality assessments

## Delegation

### Should Delegate To

- agency-security-reviewer

### Should Receive Work From

- agency-orchestrator
- agency-qa-lead
- agency-git-steward

## Escalation Triggers

- code submitted for review
- PR opened
- review request received

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
