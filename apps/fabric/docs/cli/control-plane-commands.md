---
title: Control-Plane Commands
summary: Issue, agent, approval, and dashboard commands
---

Client-side commands for managing issues, agents, approvals, and more.

## Issue Commands

```sh
# List issues
pnpm hermes-fabric issue list [--status todo,in_progress] [--assignee-agent-id <id>] [--match text]

# Get issue details
pnpm hermes-fabric issue get <issue-id-or-identifier>

# Create issue
pnpm hermes-fabric issue create --title "..." [--description "..."] [--status todo] [--priority high]

# Update issue
pnpm hermes-fabric issue update <issue-id> [--status in_progress] [--comment "..."]

# Add comment
pnpm hermes-fabric issue comment <issue-id> --body "..." [--reopen]

# Checkout task
pnpm hermes-fabric issue checkout <issue-id> --agent-id <agent-id>

# Release task
pnpm hermes-fabric issue release <issue-id>
```

## Company Commands

```sh
pnpm hermes-fabric company list
pnpm hermes-fabric company get <company-id>
pnpm hermes-fabric company current [--company-id <company-id>]

# Export to portable folder package (writes manifest + markdown files)
pnpm hermes-fabric company export <company-id> --out ./exports/acme --include company,agents

# Preview import (no writes)
pnpm hermes-fabric company import \
  <owner>/<repo>/<path> \
  --target existing \
  --company-id <company-id> \
  --ref main \
  --collision rename \
  --dry-run

# Apply import
pnpm hermes-fabric company import \
  ./exports/acme \
  --target new \
  --new-company-name "Acme Imported" \
  --include company,agents
```

With agent authentication, use `company list` or `company current` to resolve
the scoped company. `company list` first tries the board-wide list; if that is
forbidden, it falls back to `--company-id`, `HERMES_FABRIC_COMPANY_ID`, context, or
`/api/agents/me` and returns only that scoped company. `company create` requires
board/instance-admin authentication because it is an instance-wide setup
command.

## Agent Commands

```sh
pnpm hermes-fabric agent list
pnpm hermes-fabric agent get <agent-id>
```

## Skills Commands

```sh
# Browse app-shipped catalog skills without changing company state
pnpm hermes-fabric skills browse [--kind bundled|optional] [--category software-development] [--query github]
pnpm hermes-fabric skills search "pull request" [--json]

# Inspect catalog metadata and file inventory before install
pnpm hermes-fabric skills inspect github-pr-workflow

# Install a catalog skill into the company skill library
# This does not attach the skill to any agent.
pnpm hermes-fabric skills install github-pr-workflow --company-id <company-id>
pnpm hermes-fabric skills install github-pr-workflow --as pr-flow --force --company-id <company-id>

# External sources still use import instead of catalog install
pnpm hermes-fabric skills import ./skills/my-skill --company-id <company-id>
pnpm hermes-fabric skills import owner/repo/path/to/skill --company-id <company-id>

# Attach desired company skills to an agent after install/import
pnpm hermes-fabric skills agent sync <agent-id> --skill github-pr-workflow --company-id <company-id>
```

## Approval Commands

```sh
# List approvals
pnpm hermes-fabric approval list [--status pending]

# Get approval
pnpm hermes-fabric approval get <approval-id>

# Create approval
pnpm hermes-fabric approval create --type hire_agent --payload '{"name":"..."}' [--issue-ids <id1,id2>]

# Approve
pnpm hermes-fabric approval approve <approval-id> [--decision-note "..."]

# Reject
pnpm hermes-fabric approval reject <approval-id> [--decision-note "..."]

# Request revision
pnpm hermes-fabric approval request-revision <approval-id> [--decision-note "..."]

# Resubmit
pnpm hermes-fabric approval resubmit <approval-id> [--payload '{"..."}']

# Comment
pnpm hermes-fabric approval comment <approval-id> --body "..."
```

## Activity Commands

```sh
pnpm hermes-fabric activity list [--agent-id <id>] [--entity-type issue] [--entity-id <id>]
```

## Dashboard

```sh
pnpm hermes-fabric dashboard get
```

## Instance Settings

```sh
pnpm hermes-fabric instance settings:general
pnpm hermes-fabric instance settings:general:update --payload-json '{...}'
pnpm hermes-fabric instance settings:experimental
pnpm hermes-fabric instance settings:experimental:update --payload-json '{...}'
```

Experimental features are opt-in and are provided without compatibility guarantees. They may break, change, or be removed at any time. Use them at your own risk.

## Heartbeat

```sh
pnpm hermes-fabric heartbeat run --agent-id <agent-id> [--api-base http://localhost:3100]
```
