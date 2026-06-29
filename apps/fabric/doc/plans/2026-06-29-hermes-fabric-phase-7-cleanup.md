# Hermes Fabric Phase 7 Cleanup, Naming, and Packaging

Date: 2026-06-29

## Scope

Phase 7 finishes the safe rename pass without breaking workspace links, package imports, local data, or upstream MIT attribution.

## Package Namespace Audit

Current workspace package names still use the upstream namespace:

- Root package: `hermes-fabric`
- CLI package: `hermes-fabric`
- Compatibility CLI bin: `paperclipai`
- Internal packages: `@paperclipai/*`
- Adapter/plugin package names: `@paperclipai/adapter-*`, `@paperclipai/plugin-*`, `@paperclipai/*-catalog`

### Decision

Keep `@paperclipai/*` internal package names temporarily for compatibility.

### Target

Future namespace: `@hermes-fabric/*`.

### Rename gate

Do not rename internal package namespace until a dedicated migration updates all of these together:

- package names
- workspace filters
- TypeScript import specifiers
- generated lockfile entries
- bin metadata
- release/package publishing scripts
- docs and examples
- adapter/plugin registry package references
- CI/test expectations

## CLI Rename

Implemented a safe alias-first rename:

```json
{
  "name": "hermes-fabric",
  "bin": {
    "hermes-fabric": "./dist/index.js",
    "paperclipai": "./dist/index.js"
  }
}
```

Root package scripts now expose:

```bash
pnpm hermes-fabric ...
pnpm paperclipai ...
```

`paperclipai` remains as compatibility alias during the transition.

## Config Path Rename

Current runtime config and data paths still use:

```text
~/.paperclip
PAPERCLIP_* environment variables
```

### Decision

Do not move config/data in this phase.

### Reason

The current app has existing local dev data under `~/.paperclip`; moving it now risks losing embedded Postgres data, logs, secrets, auth, backups, and local instance settings.

### Future migration strategy

1. Add Hermes Fabric path support as opt-in first.
2. Copy existing `~/.paperclip` data into the new path; do not move/delete.
3. Verify config, DB, logs, storage, auth, secrets key, and backups resolve correctly.
4. Run typecheck, tests, build, and dev smoke.
5. Only then consider deprecating `PAPERCLIP_*` names.

## Docs and Assets

Updated in this phase:

- README quickstart now documents `pnpm hermes-fabric`.
- README roadmap marks Phases 3–6 complete.
- Docs site metadata now says Hermes Fabric.
- `HERMES_FABRIC.md` records rename decisions.

Deferred intentionally:

- Deep docs rewrite across historical Paperclip guides and releases.
- Full screenshot/video replacement.
- Full internal package namespace rename.
- Removing `paperclipai` command compatibility.

## Attribution

Keep upstream Paperclip MIT attribution in `LICENSE` and fork documentation.
