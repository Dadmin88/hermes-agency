# ROUTING.md — GPT Bridge

## Ownership

### Owns

- Pull-based ChatGPT escalation intake
- GPT bridge inbox queueing
- Senior/fixer handoff packets for ChatGPT
- GPT bridge task IDs and completion state
- Clear expected-output packets for live ChatGPT sessions

### Does Not Own

- Unattended OpenAI API execution
- Routine implementation that normal agency workers can complete
- Discord bot management
- Direct production changes without a claimed GPT bridge result

## Receives From

- agency-orchestrator
- agency-chief-of-staff
- agency-project-manager
- agency-traffic-manager
- any agency profile that is blocked and needs senior ChatGPT assistance

## Delegates To

- agency-orchestrator, when the task needs decomposition first
- agency-security-reviewer, when the task is a security review and ChatGPT is unavailable
- agency-software-architect, when the task is architecture-only and can be handled internally
- agency-git-steward, when completed results need source control handling

## Routing Rules

Use GPT Bridge when the work is blocked, ambiguous, high-leverage, senior-review oriented, or explicitly requested for ChatGPT. Do not route routine implementation here when a normal agency specialist can handle it.

## Escalation Format

Every GPT bridge task should include task description, reason, expected output, urgency, source task ID when available, and relevant file paths, commands, logs, or acceptance criteria.

## Preferred Tool

Use `orch_escalate_to_gpt` when available.

## Completion Contract

A GPT bridge task is complete only when a live ChatGPT session claims it and writes a result back through `hermes agency gpt-bridge complete` or the equivalent bridge API.
