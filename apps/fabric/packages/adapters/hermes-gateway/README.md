# Hermes Gateway Adapter Compatibility Shim

`@hermes-fabric/adapter-hermes-gateway` is a deprecated compatibility shim.

Use `@hermes-fabric/hermes-fabric-adapter` for new installs and import gateway
entrypoints from `@hermes-fabric/hermes-fabric-adapter/gateway`. The adapter
type remains `hermes_gateway`; only package ownership changed.

`hermes_gateway` is for an already-running Hermes API server. It does not start
the local Hermes CLI. If Hermes Fabric should launch local `hermes chat` as a child
process, use `hermes_local` from `@hermes-fabric/hermes-fabric-adapter`
instead.

The shim preserves the legacy exports for one release:

- `.`
- `./server`
- `./ui`
- `./cli`
- `./ui-parser`

These exports forward to the unified Hermes package. Existing
`@hermes-fabric/adapter-hermes-gateway` plugin installs should continue to load
during the compatibility window, but should migrate to
`@hermes-fabric/hermes-fabric-adapter` before the shim is removed.
