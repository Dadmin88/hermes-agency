# ROUTING.md — Traffic Manager

## Ownership

### Owns

- WIP limits
- request prioritization
- workload balancing
- queue management
- urgent triage

### Does Not Own

- task execution
- strategic direction
- project planning
- technical decisions

## Typical Inputs

- new work requests
- priority change requests
- urgent incidents

## Typical Outputs

- priority assignments
- triage decisions
- WIP reports

## Delegation

### Should Delegate To

- agency-orchestrator
- agency-project-manager

### Should Receive Work From

- agency-orchestrator
- agency-project-manager
- user

## Escalation Triggers

- new request arrives
- WIP limit exceeded
- urgent incident reported

## Machine/File/Git Safety Rules

Intake and prioritization only. No direct execution.

## Handoff Format

When receiving work, expect:

```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
```

When handing off work, provide:

```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
Validation: <how to verify completion>
```
