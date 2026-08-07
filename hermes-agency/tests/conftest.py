"""Shared isolation fixtures for the canonical Agency test suite."""

import pytest


@pytest.fixture(autouse=True)
def isolate_caller_hermes_profile_environment(monkeypatch):
    """Keep a caller's active Hermes profile out of each test by default."""

    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_PROFILES_DIR", raising=False)
