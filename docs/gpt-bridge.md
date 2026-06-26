# Hermes Agency GPT Bridge

The GPT Bridge is a pull-based escalation lane between Hermes Agency and a live ChatGPT session.

It does not make ChatGPT an always-on background worker. Instead, agency profiles can queue a task into a durable inbox. When Kyle opens ChatGPT and asks it to check the bridge inbox, ChatGPT can claim the task, complete the work, and write the result back.

## Flow

```text
agency profile/orchestrator
→ orch_escalate_to_gpt
→ ~/.hermes/agency/gpt_bridge/tasks/<task-id>.json
→ ChatGPT claims/completes task through Hermes bridge tools
→ orchestrator/agents read completed result
```

## Orchestrator tool

Agents should use:

```text
orch_escalate_to_gpt
```

Required input:

```json
{
  "task_description": "What ChatGPT should do"
}
```

Recommended input:

```json
{
  "task_description": "What ChatGPT should do",
  "reason": "Why GPT bridge help is needed",
  "expected_output": "Patch, review, plan, answer, etc.",
  "urgency": "normal",
  "task_id": "optional existing task id"
}
```

## CLI commands

```bash
hermes agency gpt-bridge status
hermes agency gpt-bridge inbox
hermes agency gpt-bridge inbox --active
hermes agency gpt-bridge show <task-id>
hermes agency gpt-bridge claim <task-id> --by ChatGPT
hermes agency gpt-bridge complete <task-id> "Result text" --by ChatGPT
hermes agency gpt-bridge complete <task-id> --result-file /path/to/result.md --by ChatGPT
hermes agency gpt-bridge fail <task-id> "Reason" --by ChatGPT
```

## Staff profile

The default staff roster includes:

```text
agency-gpt-bridge
```

This profile owns ChatGPT escalation packets and the GPT bridge inbox. It should not be used for routine implementation that normal agency workers can complete.

## Storage

Default storage location:

```text
~/.hermes/agency/gpt_bridge/tasks/
```

Override with:

```bash
HERMES_AGENCY_GPT_BRIDGE_DIR=/custom/path
```

## When to use it

Good uses:

- senior fixer review
- architecture synthesis
- ambiguous planning
- security-sensitive review
- cross-repo reasoning
- tasks Kyle explicitly wants ChatGPT to handle

Bad uses:

- routine implementation
- tasks requiring immediate unattended execution
- work that should go to an existing agency specialist
