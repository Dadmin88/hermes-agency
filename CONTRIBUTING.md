# Contributing

Thank you for your interest in contributing to Hermes Agency.

Hermes Agency includes a Hermes Agent plugin plus a bundled P2P SDK/runtime compatibility layer. Please keep the public product naming clear:

- User-facing project/plugin name: **Hermes Agency**
- Plugin directory/key: `hermes-agency`
- Hermes config prefix: `agency.*`
- Hermes CLI/slash commands: `hermes agency` and `/agency`
- Model tool names: `a2a_*` stay unchanged
- Lower-level compatibility names such as the Python import `agentanycast`, daemon `agentanycastd`, and env vars like `AGENTANYCAST_REGISTRY_ADDRS` should only appear where technically required

## Development Guidelines

- Run `python -m py_compile hermes-agency/*.py` when plugin files change.
- Run `pytest hermes-agency/tests/test_unit.py -q` when plugin behavior changes.
- Run `ruff check .` and `ruff format --check .` before submitting SDK/core changes.
- All public SDK APIs should have type hints and docstrings.
- Tests use pytest with `asyncio_mode = "auto"`.
- Do not modify files under `src/agentanycast/_generated/` unless regenerating them from the protobuf source.
- Do not commit daemon state, local profile config, peer IDs, Discord channel IDs, API keys, tokens, or machine-specific paths.

## Required CI Checks

All relevant checks should pass before a PR is merged:

- **Hermes Agency Plugin** — plugin compile + unit tests
- **proto-freshness** — generated stubs match proto definitions
- **lint** — `ruff check` and `ruff format --check`
- **type-check** — `mypy` in strict mode
- **test** — pytest suite
