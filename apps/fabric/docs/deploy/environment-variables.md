---
title: Environment Variables
summary: Full environment variable reference
---

All environment variables that Hermes Fabric uses for server configuration.

## Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3100` | Server port |
| `HERMES_FABRIC_BIND` | `loopback` | Reachability preset: `loopback`, `lan`, `tailnet`, or `custom` |
| `HERMES_FABRIC_BIND_HOST` | (unset) | Required when `HERMES_FABRIC_BIND=custom` |
| `HOST` | `127.0.0.1` | Legacy host override; prefer `HERMES_FABRIC_BIND` for new setups |
| `DATABASE_URL` | (embedded) | PostgreSQL connection string |
| `HERMES_FABRIC_HOME` | `~/.hermes-fabric` | Base directory for all Hermes Fabric data |
| `HERMES_FABRIC_INSTANCE_ID` | `default` | Instance identifier (for multiple local instances) |
| `HERMES_FABRIC_DEPLOYMENT_MODE` | `local_trusted` | Runtime mode override |
| `HERMES_FABRIC_DEPLOYMENT_EXPOSURE` | `private` | Exposure policy when deployment mode is `authenticated` |
| `HERMES_FABRIC_API_URL` | (auto-derived) | Hermes Fabric API base URL. When set externally (e.g., via Kubernetes ConfigMap, load balancer, or reverse proxy), the server preserves the value instead of deriving it from the listen host and port. Useful for deployments where the public-facing URL differs from the local bind address. |

## Secrets

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_FABRIC_SECRETS_MASTER_KEY` | (from file) | 32-byte encryption key (base64/hex/raw) |
| `HERMES_FABRIC_SECRETS_MASTER_KEY_FILE` | `~/.hermes-fabric/.../secrets/master.key` | Path to key file |
| `HERMES_FABRIC_SECRETS_STRICT_MODE` | `false` | Require secret refs for sensitive env vars |

## Agent Runtime (Injected into agent processes)

These are set automatically by the server when invoking agents:

| Variable | Description |
|----------|-------------|
| `HERMES_FABRIC_AGENT_ID` | Agent's unique ID |
| `HERMES_FABRIC_COMPANY_ID` | Company ID |
| `HERMES_FABRIC_API_URL` | Hermes Fabric API base URL (inherits the server-level value; see Server Configuration above) |
| `HERMES_FABRIC_API_KEY` | Short-lived JWT for API auth |
| `HERMES_FABRIC_RUN_ID` | Current heartbeat run ID |
| `HERMES_FABRIC_TASK_ID` | Issue that triggered this wake |
| `HERMES_FABRIC_WAKE_REASON` | Wake trigger reason |
| `HERMES_FABRIC_WAKE_COMMENT_ID` | Comment that triggered this wake |
| `HERMES_FABRIC_APPROVAL_ID` | Resolved approval ID |
| `HERMES_FABRIC_APPROVAL_STATUS` | Approval decision |
| `HERMES_FABRIC_LINKED_ISSUE_IDS` | Comma-separated linked issue IDs |

## LLM Provider Keys (for adapters)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (for Claude Local adapter) |
| `OPENAI_API_KEY` | OpenAI API key (for Codex Local adapter) |
