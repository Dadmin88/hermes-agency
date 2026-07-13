PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff

# Canonical non-integration Agency suite (shared by CI and release).
AGENCY_TESTS = \
	hermes-agency/tests/test_unit.py \
	hermes-agency/tests/test_golden_path.py \
	hermes-agency/tests/test_model_sets.py \
	hermes-agency/tests/test_extended_status_discord.py \
	hermes-agency/tests/test_keryx_transport.py \
	hermes-agency/tests/test_node_lifecycle.py \
	hermes-agency/tests/test_default_staff.py \
	hermes-agency/tests/test_departments.py \
	hermes-agency/tests/test_agent_lifecycle.py \
	hermes-agency/tests/test_pool_manager.py \
	hermes-agency/tests/test_pool_process_safety.py \
	hermes-agency/tests/test_pool_profile_validation.py \
	hermes-agency/tests/test_pool_provider_guard.py \
	hermes-agency/tests/test_pool_security.py \
	hermes-agency/tests/test_pool_profile_paths.py \
	hermes-agency/tests/test_p5_export_server_security.py \
	hermes-agency/tests/test_incoming_reauthorization.py \
	hermes-agency/tests/test_remote_output_redaction.py \
	hermes-agency/tests/test_remote_subprocess_environment.py \
	hermes-agency/tests/test_keryx_channel_ownership.py

POOL_TESTS = \
	hermes-agency/tests/test_pool_manager.py \
	hermes-agency/tests/test_pool_process_safety.py \
	hermes-agency/tests/test_pool_profile_validation.py \
	hermes-agency/tests/test_pool_provider_guard.py \
	hermes-agency/tests/test_pool_security.py

.PHONY: test test-sdk test-agency test-pool lint lint-agency integration-agency integration-agency-full

test: test-sdk test-agency

test-sdk:
	$(PYTEST) tests/ -m "not integration"

test-agency:
	$(PYTEST) $(AGENCY_TESTS) -q -m "not integration"

test-pool:
	$(PYTEST) $(POOL_TESTS) -q -m "not integration"

lint: lint-agency

lint-agency:
	$(RUFF) check hermes-agency/
	$(RUFF) format --check hermes-agency/

integration-agency:
	$(PYTHON) hermes-agency/tests/test_e2e.py

integration-agency-full:
	$(PYTHON) hermes-agency/tests/test_e2e_full.py
