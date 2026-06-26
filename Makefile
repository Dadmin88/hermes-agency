PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff

.PHONY: test test-sdk test-agency lint lint-agency integration-agency integration-agency-full
.PHONY: dashboard-install dashboard-dev dashboard-build dashboard-check

test: test-sdk test-agency

test-sdk:
	$(PYTEST) tests/ -m "not integration"

test-agency:
	$(PYTEST) hermes-agency/tests/test_unit.py -q -m "not integration"
	$(PYTEST) hermes-agency/tests/test_dashboard.py -q -m "not integration"
	$(PYTEST) hermes-agency/tests/test_dashboard_cli.py -q -m "not integration"

lint: lint-agency

lint-agency:
	$(RUFF) check hermes-agency/
	$(RUFF) format --check hermes-agency/

integration-agency:
	$(PYTHON) hermes-agency/tests/test_e2e.py

integration-agency-full:
	$(PYTHON) hermes-agency/tests/test_e2e_full.py

# Dashboard targets
dashboard-install:
	cd web/agency-dashboard && npm install

dashboard-dev:
	cd web/agency-dashboard && npm run dev

dashboard-build:
	cd web/agency-dashboard && npm run build

dashboard-check:
	cd web/agency-dashboard && npm run typecheck
	$(PYTEST) hermes-agency/tests/test_dashboard.py -q
	$(PYTEST) hermes-agency/tests/test_dashboard_cli.py -q
