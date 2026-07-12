# @Hermes Fabricai/create-Hermes Fabric-plugin

Scaffolding tool for creating new Hermes Fabric plugins.

```bash
npx @hermes-fabric/create-fabric-plugin my-plugin
```

Or with options:

```bash
npx @hermes-fabric/create-fabric-plugin @acme/my-plugin \
  --template connector \
  --category connector \
  --display-name "Acme Connector" \
  --description "Syncs Acme data into HermesFabric" \
  --author "Acme Inc"
```

Supported templates: `default`, `connector`, `workspace`
Supported categories: `connector`, `workspace`, `automation`, `ui`

Generates:
- typed manifest + worker entrypoint
- example UI widget using the supported `@hermes-fabric/plugin-sdk/ui` hooks
- test file using `@hermes-fabric/plugin-sdk/testing`
- `esbuild` and `rollup` config files using SDK bundler presets
- dev server script for hot-reload (`fabric-plugin-dev-server`)

The scaffold starts with plain React elements so the generated plugin stays minimal. For Hermes Fabric-native controls, import shared host components such as `MarkdownEditor`, `FileTree`, `AssigneePicker`, and `ProjectPicker` from `@hermes-fabric/plugin-sdk/ui`.

Inside this repo, the generated package uses `@hermes-fabric/plugin-sdk` via `workspace:*`.

Outside this repo, the scaffold snapshots `@hermes-fabric/plugin-sdk` from your local Hermes Fabric checkout into a `.fabric-sdk/` tarball and points the generated package at that local file by default. You can override the SDK source explicitly:

```bash
node packages/plugins/create-fabric-plugin/dist/bin.js @acme/my-plugin \
  --output /absolute/path/to/plugins \
  --sdk-path /absolute/path/to/fabric/packages/plugins/sdk
```

That gives you an outside-repo local development path before the SDK is published to npm.

## Workflow after scaffolding

```bash
cd my-plugin
pnpm install
pnpm dev       # watch worker + manifest + ui bundles
pnpm dev:ui    # local UI preview server with hot-reload events
pnpm test
```
