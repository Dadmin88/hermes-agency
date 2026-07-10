# Contributing

Thank you for your interest in contributing to Hermes Agency.

Hermes Agency is a Hermes Agent plugin and local operations layer for managed multi-agent teams. Keryx is the primary transport and its Python SDK is vendored in this repository at `src/keryx/`; AgentAnycast under `src/agentanycast/` is retained for legacy/fallback compatibility only.

## Development Setup

From the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs the plugin and the vendored Keryx SDK. Do not require a sibling `Hermes_Keryx/sdk/python` editable install for normal Agency work. External Keryx runtime binaries/services (`keryxd`, relay, registry) are separate deployment dependencies.

## Contribution Guidelines

- Keep Hermes Agency product-first in public docs, issue summaries, PR summaries, and handoffs.
- Describe Keryx as the primary transport and AgentAnycast as legacy/fallback only.
- Keep transport imports lazy so Hermes plugin discovery can succeed when optional runtime pieces are unavailable.
- Keep examples generic. Use placeholders such as `<profile-name>`, `<daemon-endpoint>`, `<relay-endpoint>`, `<registry-address>`, and `<peer-id>`.
- Never commit API keys, tokens, private relay addresses, real peer IDs, maintainer-local paths, private hostnames, gateway logs, Discord channel IDs, or raw environment dumps.
- Do not modify generated proto files unless the generation source and regeneration command are part of the change.

## Validation

Run the fastest relevant checks for your change, then broader checks before proposing a PR:

```bash
ruff check .
ruff format --check .
make test-agency
python -m pytest hermes-agency/tests/test_keryx_transport.py -q
python -m pip check
```

For broader transport or packaging changes, also run:

```bash
make test-sdk
python -m pytest
```

Live relay/daemon checks are manual and should be run only when an appropriate Keryx or explicit legacy AgentAnycast environment is intended:

```bash
make integration-agency
make integration-agency-full
```

Default pytest commands skip tests marked `integration`; use `pytest -m integration` or the Makefile integration targets for live checks.

## Required CI Checks

All of the following should pass before a PR can be merged:

- **proto-freshness** — generated stubs match proto definitions when proto files change
- **lint** — `ruff check` and `ruff format --check`
- **type-check** — `mypy` in strict mode when applicable
- **test** — relevant pytest suites
- **dependency health** — `python -m pip check`
