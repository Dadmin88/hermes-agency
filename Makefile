PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff

.PHONY: test test-sdk test-agency lint lint-agency integration-agency integration-agency-full

test: test-sdk test-agency

test-sdk:
	$(PYTEST) tests/ -m "not integration"

test-agency:
	$(PYTEST) hermes-agency/tests/test_unit.py -q -m "not integration"

lint: lint-agency

lint-agency:
	$(RUFF) check hermes-agency/
	$(RUFF) format --check hermes-agency/

integration-agency:
	$(PYTHON) hermes-agency/tests/test_e2e.py

integration-agency-full:
	$(PYTHON) hermes-agency/tests/test_e2e_full.py
