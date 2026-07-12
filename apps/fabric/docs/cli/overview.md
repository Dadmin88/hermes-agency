---
title: CLI Overview
summary: CLI installation and setup
---

The Hermes Fabric CLI handles instance setup, diagnostics, and control-plane operations.

## Usage

```sh
pnpm hermes-fabric --help
```

## Global Options

All commands support:

| Flag | Description |
|------|-------------|
| `--data-dir <path>` | Local Hermes Fabric data root (isolates from `~/.hermes-fabric`) |
| `--api-base <url>` | API base URL |
| `--api-key <token>` | API authentication token |
| `--context <path>` | Context file path |
| `--profile <name>` | Context profile name |
| `--json` | Output as JSON |

Company-scoped commands also accept `--company-id <id>`.

For clean local instances, pass `--data-dir` on the command you run:

```sh
pnpm hermes-fabric run --data-dir ./tmp/fabric-dev
```

## Context Profiles

Store defaults to avoid repeating flags:

```sh
# Set defaults
pnpm hermes-fabric context set --api-base http://localhost:3100 --company-id <id>

# View current context
pnpm hermes-fabric context show

# List profiles
pnpm hermes-fabric context list

# Switch profile
pnpm hermes-fabric context use default
```

To avoid storing secrets in context, use an env var:

```sh
pnpm hermes-fabric context set --api-key-env-var-name HERMES_FABRIC_API_KEY
export HERMES_FABRIC_API_KEY=...
```

Secret operations are available under `hermes-fabric secrets`:

```sh
pnpm hermes-fabric secrets declarations --company-id <company-id> --kind secret
pnpm hermes-fabric secrets create --company-id <company-id> --name anthropic-api-key --value-env ANTHROPIC_API_KEY
pnpm hermes-fabric secrets link --company-id <company-id> --name prod-stripe-key --provider aws_secrets_manager --external-ref <provider-ref>
pnpm hermes-fabric secrets doctor --company-id <company-id>
pnpm hermes-fabric secrets migrate-inline-env --company-id <company-id> --apply
```

Context is stored at `~/.hermes-fabric/context.json`.

## Command Categories

The CLI has two categories:

1. **[Setup commands](/cli/setup-commands)** — instance bootstrap, diagnostics, configuration
2. **[Control-plane commands](/cli/control-plane-commands)** — issues, agents, approvals, activity
