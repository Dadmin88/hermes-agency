## Summary

<!-- Brief description of the changes. -->

## Motivation

<!-- Why is this change needed? Link to relevant issue(s). -->

Fixes DeployFaith/Hermes_Agency#

## Changes

-

## Testing

- [ ] `python -m py_compile hermes-agency/*.py` passes when plugin files changed
- [ ] `pytest hermes-agency/tests/test_unit.py -q` passes when plugin files changed
- [ ] `ruff check .` passes when SDK/core files changed
- [ ] `ruff format --check .` passes when SDK/core files changed
- [ ] `pytest tests/ -v` passes when SDK/core files changed
- [ ] Manually verified live P2P behavior if networking/runtime behavior changed

## Checklist

- [ ] Self-reviewed the diff
- [ ] Updated documentation if behavior/config/commands changed
- [ ] Preserved naming boundaries: Hermes plugin is `hermes-agency`/`agency.*`; SDK/runtime names remain `agentanycast`/`agentanycastd`
- [ ] No secrets, local peer IDs, Discord channel IDs, profile-private paths, or daemon state were committed
