# Contributing

Thank you for your interest in contributing to AgentAnycast!

Please see the [Contributing Guide](https://github.com/AgentAnycast/agentanycast/blob/main/CONTRIBUTING.md) in the main repository for guidelines on:

- Development workflow (fork → branch → PR → squash merge)
- Coding standards and commit message conventions
- Cross-repository changes
- CLA requirements

## Python SDK-Specific Guidelines

- Run `ruff check .` and `ruff format --check .` before submitting
- All public APIs must have type hints and docstrings
- Tests use pytest with `asyncio_mode = "auto"`
- Do not modify files under `src/agentanycast/_generated/` — those are auto-generated from proto

## Required CI Checks

All of the following must pass before a PR can be merged:

- **proto-freshness** — Verify generated stubs match proto definitions
- **lint** — `ruff check` and `ruff format --check`
- **type-check** — `mypy` in strict mode
- **test** — Full pytest suite
