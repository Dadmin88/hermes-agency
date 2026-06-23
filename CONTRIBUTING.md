# Contributing

Thank you for your interest in contributing to AgentAnycast!

Please see the [Contributing Guide](https://github.com/AgentAnycast/agentanycast/blob/main/CONTRIBUTING.md) in the main repository for guidelines on:

- Development workflow (fork → branch → PR → squash merge)
- Coding standards and commit message conventions
- Cross-repository changes
- CLA requirements

## Python SDK-Specific Guidelines

- Install dev prerequisites with `python -m pip install -e ".[dev]`
- Run `make test` before submitting SDK/plugin changes
- Run `make test-agency` for the Hermes Agency plugin unit suite
- Run `make lint-agency` for Hermes Agency Ruff checks
- Run live Hermes Agency checks manually with `make integration-agency` or `make integration-agency-full` only when a local daemon/relay environment is intended
- Run `ruff check .` and `ruff format --check .` before submitting
- All public APIs must have type hints and docstrings
- Tests use pytest with `asyncio_mode = "auto"`
- Default pytest commands skip tests marked `integration`; use `pytest -m integration` or the Makefile integration targets for live checks
- Do not modify files under `src/agentanycast/_generated/` — those are auto-generated from proto

## Required CI Checks

All of the following must pass before a PR can be merged:

- **proto-freshness** — Verify generated stubs match proto definitions
- **lint** — `ruff check` and `ruff format --check`
- **type-check** — `mypy` in strict mode
- **test** — Full pytest suite
