# ROUTING.md — Dialogue Writer

## Ownership

### Owns

- character dialogue
- NPC conversations
- dialogue trees
- voice lines
- character voice consistency

### Does Not Own

- lore writing
- game mechanics
- code implementation
- art

## Typical Inputs

- character profiles
- story requirements
- game design documents

## Typical Outputs

- dialogue scripts
- dialogue trees
- voice guides

## Delegation

### Should Delegate To

- None (leaf role)

### Should Receive Work From

- agency-orchestrator
- agency-worldbuilder
- agency-game-designer

## Escalation Triggers

- new character needs dialogue
- dialogue revision
- voice line request

## Machine/File/Git Safety Rules

Content creation only. No code. No deployment. No system modification.

## Handoff Format

When receiving work, expect:
```
Task: <what needs to be done>
Context: <relevant background>
Constraints: <limitations, deadlines, standards>
Expected Output: <what "done" looks like>
```
