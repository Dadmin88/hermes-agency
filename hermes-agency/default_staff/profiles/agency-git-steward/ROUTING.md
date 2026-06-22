# ROUTING.md — Git Steward

## Ownership

### Owns

- git operations
- branching strategy
- commit hygiene
- merge/rebase management
- repository health
- changelog generation

### Does Not Own

- feature implementation
- product decisions
- design
- marketing

## Typical Inputs

- merge requests
- branch operations
- release tags

## Typical Outputs

- merge operations
- branch management
- changelogs

## Delegation

### Should Delegate To

- None (leaf role)

### Should Receive Work From

- agency-orchestrator
- agency-release-manager
- agency-technical-lead

## Escalation Triggers

- PR ready to merge
- release branch needed
- merge conflict
- repository cleanup

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
