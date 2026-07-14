# Hermes Agency Typing Baseline

**Captured:** 2026-07-14
**Status:** Diagnostic backlog; not a passing CI gate

## Supported passing gate

The supported strict Mypy gate is the source-package gate already used by CI:

```bash
python -m mypy src/ --exclude '_generated'
```

It covers the Keryx SDK and other conventional packages under `src/`. It currently passes. The narrower reproducible Keryx-only command is:

```bash
python -m mypy src/keryx
```

## Plugin diagnostic command

The plugin source is stored in the distribution-mapped directory `hermes-agency/`, whose hyphen is not a valid Python package name. Passing that directory directly to Mypy is therefore not supported. The current diagnostic invocation treats files as explicit package bases and excludes packaged staff assets and tests:

```bash
MYPYPATH=src:hermes-agency python -m mypy \
  --explicit-package-bases \
  --exclude 'hermes-agency/(default_staff|tests)/' \
  hermes-agency
```

Current baseline: **824 errors in 53 files while checking 61 source files**.

| Error code | Count |
|---|---:|
| `attr-defined` | 288 |
| `import-not-found` | 140 |
| `no-untyped-call` | 126 |
| `no-untyped-def` | 72 |
| `no-any-return` | 63 |
| `import-untyped` | 46 |
| `union-attr` | 17 |
| `assignment` | 14 |
| `has-type` | 14 |
| `unused-ignore` | 12 |
| `index` | 9 |
| `misc` | 9 |
| `arg-type` | 9 |
| Other | 5 |

Largest file backlogs:

| File | Errors |
|---|---:|
| `node_lifecycle.py` | 110 |
| `incoming_queue.py` | 108 |
| `pool/manager.py` | 102 |
| `kanban_sync.py` | 51 |
| `node_manager.py` | 51 |
| `registry_client.py` | 47 |

The detailed diagnostic log is retained outside the repository at:

`/home/dadmin/.cache/hermes-agency-audit/final-state/mypy-agency-core.log`

## Remediation order

1. Define stubs or typed protocols for Hermes runtime/plugin imports; this should remove most `import-not-found` and cascading `attr-defined` errors.
2. Type the node lifecycle and incoming-queue mixin contracts.
3. Type pool manager process/config state.
4. Type registry, Kanban, and team-discovery clients.
5. Type CLI/tool handlers and remove unnecessary ignores.
6. Re-run the diagnostic command after each subsystem.
7. Add the plugin to required CI only when the command is stable and reaches zero errors.

Do not suppress the 824-error baseline globally or claim the plugin is strictly typed. New code should continue to pass Ruff and should add annotations where its runtime interfaces are known.
