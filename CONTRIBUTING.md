# Contributing to Hermes Agency

Thanks for contributing to Hermes Agency.

Hermes Agency is the product in this repository. Keryx is the primary transport; AgentAnycast is legacy/fallback only.

## Development workflow

1. Fork / branch from `main`
2. Make focused changes with tests
3. Run validation (below)
4. Open a PR with a clear motivation and test plan
5. Squash-merge when CI is green

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs:

- the Hermes Agency plugin package
- the vendored Keryx Python SDK from `src/keryx/`
- legacy AgentAnycast sources under `src/agentanycast/` (fallback path)

External Keryx binaries (`keryxd`, `keryx-relay`) are built from the separate `hermes-keryx` repository when you need a live daemon/relay.

## Coding standards

- Prefer clear, typed Python for public APIs
- Keep transport SDK imports lazy at plugin load boundaries
- Prefer direct Keryx imports for new transport code:
  - `from keryx import KeryxNode, AgentCard, Skill`
- Do not modify generated stubs (`src/agentanycast/_generated/`, Keryx generated protos) by hand unless the change is intentionally regenerating them
- Keep examples generic (no real peer IDs, private hostnames, secrets, or maintainer-local paths)
- Commit messages: concise, imperative, scoped (`feat(agency): ...`, `fix(ci): ...`, `docs: ...`)

## Validation before PR

```bash
ruff check .
ruff format --check .
make test-agency
python -m pytest hermes-agency/tests/test_unit.py -q -m "not integration"
python -m pytest hermes-agency/tests/test_keryx_transport.py -q
python -m pip check
```

This command set is the default green CI / seam-test rung. It proves the repository checks that actually ran, including the in-process Agency golden path, but it does not by itself prove live daemon, Docker, or cross-machine Keryx behavior.

Model-set changes:

```bash
python -m pytest -q hermes-agency/tests/test_model_sets.py
```

Optional live integration (requires local Keryx or legacy AgentAnycast runtime):

```bash
make integration-agency
# or
make integration-agency-full
```

Default pytest configuration skips `integration` tests.

Use `docs/qa-validation-ladder.md` to decide when local-daemon, Docker, real-profile/manual, or opt-in live Keryx E2E validation is also required for the change you are making.

## Required CI checks

Typical required checks:

- **lint** — Ruff check/format
- **type-check** — mypy (where configured)
- **test** — Agency plugin unit suite across supported Python versions
- **security audit** — dependency advisory scan
- **proto freshness** — when applicable for generated stubs

## Documentation

If your change affects operators or contributors, update the relevant docs in the same PR:

- `README.md`
- `AGENTS.md`
- `hermes-agency/README.md`
- `hermes-agency/AGENTS.md`
- `llms.txt`
- `CHANGELOG.md` for user-visible changes

## Cross-repository Keryx work

| Concern | Where |
|---------|-------|
| Rust daemon/relay/CLI/protocol | `hermes-keryx` repo |
| Agency plugin/product behavior | this repo |
| Python SDK packaging inside Agency | vendored `src/keryx/` (sync from hermes-keryx when needed) |
| Migration/dual-run scripts | `hermes-keryx/scripts/` |

When changing the Keryx SDK API, update Agency call sites and docs in the same integration pass.

## Safety

- Do not weaken remote-task defaults without an explicit security review
- Do not commit secrets, tokens, private multiaddrs, real peer IDs, or private hostnames
- Prefer loopback binds for local management endpoints
