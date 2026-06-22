# Hermes Agency Relay Registration Reliability — Phase 1 Completion Notes

## Scope

Phase 1 canonicalizes the relay skill-registry re-registration reliability fix in the plugin source and validates it with unit tests.

## Source files reviewed/updated

- `hermes-agency/node_manager.py`
- `hermes-agency/tests/test_unit.py`

## Canonical behavior confirmed in `node_manager.py`

- Re-registration interval remains below the relay TTL:
  - `REGISTRY_REREGISTER_INTERVAL_SECONDS = 20`
- Failure backoff constants exist:
  - `REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS = 1`
  - `REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS = 60`
  - `REGISTRY_REREGISTER_FAILURE_LOG_EVERY = 5`
  - `REGISTRY_HEALTHY_WINDOW_SECONDS = 60`
- `NodeState` tracks registration health:
  - `last_registration_time`
  - `consecutive_failures`
  - `next_retry_at`
  - `registration_healthy`
  - `registry_reregister_loop_exited`
- `_register_skills_with_registries()` returns structured success/failure/skipped data.
- `_registry_reregister_loop()` catches per-iteration exceptions and does not die from normal registry failures.
- Registry refresh failures log WARNING messages with retry/backoff details.
- Every 5 consecutive failures logs an additional visible WARNING.
- Successful registration resets `consecutive_failures` and logs recovery after prior failures.
- Unexpected loop exit sets `registry_reregister_loop_exited=True` and logs CRITICAL.
- `_registry_reregister_done()` records unexpected task exit and starts a replacement task when the node is still running.
- `manager.info()` exposes health under `registration.registry_refresh`.

## Tests confirmed in `test_unit.py`

- Registry address parsing.
- Successful registry refresh posts the card to each configured registry.
- Successful refresh updates health state:
  - `last_registration_time is not None`
  - `consecutive_failures == 0`
  - `registration_healthy is True`
- Registry refresh failure records failure state:
  - `consecutive_failures` increments
  - `next_retry_at is not None`
  - `registration_healthy is False` when no recent success exists
- Every-5-failures warning is emitted.
- Recovery resets `consecutive_failures` to `0` and logs recovery.

## Validation commands run

```bash
cd ~/src/hermes-agentanycast
python3 -m py_compile hermes-agency/node_manager.py hermes-agency/tools.py hermes-agency/tests/test_unit.py
/tmp/hermes-agency-test-venv/bin/python -m pytest hermes-agency/tests/test_unit.py -q
```

## Validation result

```text
70 passed in 1.18s
```

## Patch artifact

Because the repository already contains substantial unrelated uncommitted/untracked Hermes Agency work, I did not create a git commit from the dirty working tree. Instead, I saved a focused runtime patch generated from the VPS pre-fix backup to the patched VPS runtime file:

- `docs/patches/agency-relay-registration-reliability.vps-node-manager.diff`

This patch captures the relay registration reliability delta only for the deployed VPS `node_manager.py` hotfix.

## Phase 1 status

Complete.
