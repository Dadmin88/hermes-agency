# `@hermes-fabric/plugin-novita-sandbox`

Published Novita Agent Sandbox provider plugin for Hermes Fabric.

This package lives in the Hermes Fabric monorepo, but it is intentionally excluded from the root `pnpm` workspace and shaped to publish and install like a standalone npm package. That means operators can install it from the Plugins page by package name, and the host will fetch its transitive dependencies at install time without adding lockfile churn to the Hermes Fabric repo.

## Install

From a Hermes Fabric instance, install:

```text
@hermes-fabric/plugin-novita-sandbox
```

The host plugin installer runs `npm install` into the managed plugin directory, so package dependencies such as `novita-sandbox` are pulled in during installation.

## Configuration

Configure Novita from `Instance Settings -> Environments`, not from the plugin's plugin page.

- Put the Novita API key on the sandbox environment itself.
- When you save an environment, Hermes Fabric stores pasted API keys as company secrets.
- `NOVITA_API_KEY` remains an optional host-level fallback when an environment omits the key.

## Local development

```bash
cd packages/plugins/sandbox-providers/novita
pnpm install --ignore-workspace --no-lockfile
pnpm build
pnpm test
pnpm typecheck
```

These commands assume the repo root has already been installed once so the local `@hermes-fabric/plugin-sdk` workspace package is available to the compiler during development.

## Package layout

- `src/manifest.ts` declares the sandbox-provider driver metadata
- `src/plugin.ts` implements the environment lifecycle hooks
- `src/worker.ts` boots the plugin under the host worker runtime
- `fabricPlugin.manifest` and `fabricPlugin.worker` point the host at the built plugin entrypoints in `dist/`
