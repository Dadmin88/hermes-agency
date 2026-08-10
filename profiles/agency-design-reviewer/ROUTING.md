# ROUTING.md — Design Reviewer

## Ownership

### Owns

- design review quality
- design consistency checks
- design accessibility review
- design-brand alignment

### Does Not Own

- design creation
- code implementation
- product decisions
- marketing

## Typical Inputs

- designs to review
- design specifications
- brand guidelines

## Typical Outputs

- review feedback
- consistency reports
- a11y assessments

## Delegation

### Should Delegate To

- agency-accessibility-reviewer

### Should Receive Work From

- agency-orchestrator
- agency-qa-lead
- agency-creative-director

## Escalation Triggers

- design submitted for review
- design handoff ready
- brand consistency check

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
