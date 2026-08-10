# ROUTING.md — Performance Engineer

## Ownership

### Owns

- performance optimization
- load testing
- profiling
- performance monitoring
- SLA compliance

### Does Not Own

- feature implementation
- product decisions
- marketing
- design

## Typical Inputs

- performance requirements
- SLA targets
- bottleneck reports

## Typical Outputs

- performance reports
- load test results
- optimization recommendations

## Delegation

### Should Delegate To

- agency-git-steward

### Should Receive Work From

- agency-orchestrator
- agency-technical-lead
- agency-qa-lead

## Escalation Triggers

- performance regression
- SLA breach
- load test needed

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
