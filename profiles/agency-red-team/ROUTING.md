# ROUTING.md — Red Team

## Ownership

### Owns

- adversarial testing
- penetration testing
- attack simulation
- incident response testing
- security control validation

### Does Not Own

- feature implementation
- security remediation
- product decisions
- infrastructure operations

## Typical Inputs

- security scope
- test scenarios
- system access

## Typical Outputs

- pentest reports
- attack simulations
- security recommendations

## Delegation

### Should Delegate To

- None (leaf role)

### Should Receive Work From

- agency-orchestrator
- agency-security-engineer
- agency-qa-lead

## Escalation Triggers

- security assessment scheduled
- new system needs pen test
- incident response drill

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
