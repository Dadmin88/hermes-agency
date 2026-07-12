---
title: Setup Commands
summary: Onboard, run, doctor, and configure
---

Instance setup and diagnostics commands.

## `hermes-fabric run`

One-command bootstrap and start:

```sh
pnpm hermes-fabric run
```

Does:

1. Auto-onboards if config is missing
2. Runs `hermes-fabric doctor` with repair enabled
3. Starts the server when checks pass

Choose a specific instance:

```sh
pnpm hermes-fabric run --instance dev
```

## `hermes-fabric onboard`

Interactive first-time setup:

```sh
pnpm hermes-fabric onboard
```

If Hermes Fabric is already configured, rerunning `onboard` keeps the existing config in place. Use `hermes-fabric configure` to change settings on an existing install.

First prompt:

1. `Quickstart` (recommended): local defaults (embedded database, no LLM provider, local disk storage, default secrets)
2. `Advanced setup`: full interactive configuration

Start immediately after onboarding:

```sh
pnpm hermes-fabric onboard --run
```

Non-interactive defaults + immediate start (opens browser on server listen):

```sh
pnpm hermes-fabric onboard --yes
```

On an existing install, `--yes` now preserves the current config and just starts Hermes Fabric with that setup.

## `hermes-fabric doctor`

Health checks with optional auto-repair:

```sh
pnpm hermes-fabric doctor
pnpm hermes-fabric doctor --repair
```

Validates:

- Server configuration
- Database connectivity
- Secrets adapter configuration, including AWS Secrets Manager non-secret env
  config when selected
- Storage configuration
- Missing key files

## `hermes-fabric configure`

Update configuration sections:

```sh
pnpm hermes-fabric configure --section server
pnpm hermes-fabric configure --section secrets
pnpm hermes-fabric configure --section storage
```

`--section secrets` updates the deployment-level provider used as the fallback
for secrets that do not target a specific company vault. Per-company provider
vaults (named instances, default vault selection, multiple vaults per provider,
coming-soon GCP/Vault) live in the board UI under
`Company Settings → Secrets → Provider vaults` and the
`/api/companies/{companyId}/secret-provider-configs` API.

## `hermes-fabric env`

Show resolved environment configuration:

```sh
pnpm hermes-fabric env
```

This now includes bind-oriented deployment settings such as `HERMES_FABRIC_BIND` and `HERMES_FABRIC_BIND_HOST` when configured.

## `hermes-fabric allowed-hostname`

Allow a private hostname for authenticated/private mode:

```sh
pnpm hermes-fabric allowed-hostname my-tailscale-host
```

## Local Storage Paths

| Data | Default Path |
|------|-------------|
| Config | `~/.hermes-fabric/instances/default/config.json` |
| Database | `~/.hermes-fabric/instances/default/db` |
| Logs | `~/.hermes-fabric/instances/default/logs` |
| Storage | `~/.hermes-fabric/instances/default/data/storage` |
| Secrets key | `~/.hermes-fabric/instances/default/secrets/master.key` |

Override with:

```sh
HERMES_FABRIC_HOME=/custom/home HERMES_FABRIC_INSTANCE_ID=dev pnpm hermes-fabric run
```

Or pass `--data-dir` directly on any command:

```sh
pnpm hermes-fabric run --data-dir ./tmp/fabric-dev
pnpm hermes-fabric doctor --data-dir ./tmp/fabric-dev
```
