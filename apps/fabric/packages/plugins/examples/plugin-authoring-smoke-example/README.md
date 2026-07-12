# Plugin Authoring Smoke Example

A Hermes Fabric plugin

## Development

```bash
pnpm install
pnpm dev            # watch builds
pnpm dev:ui         # local dev server with hot-reload events
pnpm test
```

## Install Into Hermes Fabric

```bash
pnpm hermes-fabric plugin install ./
```

## Build Options

- `pnpm build` uses esbuild presets from `@hermes-fabric/plugin-sdk/bundlers`.
- `pnpm build:rollup` uses rollup presets from the same SDK.
