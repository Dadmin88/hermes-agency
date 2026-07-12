# @Hermes Fabricai/ui

Published static assets for the Hermes Fabric board UI.

## What gets published

The npm package contains the production build under `dist/`. It does not ship the UI source tree or workspace-only dependencies.

## Storybook

Storybook config, stories, and fixtures live under `ui/storybook/`.

```sh
pnpm --filter @hermes-fabric/ui storybook
pnpm --filter @hermes-fabric/ui build-storybook
```

## Typical use

Install the package, then serve or copy the built files from `node_modules/@hermes-fabric/ui/dist`.
