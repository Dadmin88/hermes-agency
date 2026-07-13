"""Outbound remote text must redact secrets and bound size."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_outbound():
    path = PLUGIN_DIR / "outbound_security.py"
    spec = importlib.util.spec_from_file_location("agency_outbound_security", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agency_outbound_security"] = module
    spec.loader.exec_module(module)
    return module


def test_redacts_bearer_and_api_keys():
    sec = _load_outbound()
    text = "Authorization: Bearer super-secret-token-value\napi_key=sk-abc1234567890xyz"
    out = sec.sanitize_remote_text(text, kind="artifact")
    assert "super-secret-token-value" not in out
    assert "sk-abc1234567890xyz" not in out
    assert "<redacted>" in out


def test_redacts_url_credentials_and_home_paths():
    sec = _load_outbound()
    text = "connect https://user:pass@example.com/v1 from /home/kyle/secret/project"
    out = sec.sanitize_remote_text(text, kind="progress")
    assert "user:pass" not in out
    assert "/home/kyle" not in out
    assert "<redacted>" in out


def test_redacts_private_key_blocks():
    sec = _load_outbound()
    text = "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg...\n-----END PRIVATE KEY-----"
    out = sec.sanitize_remote_text(text, kind="error")
    assert "MIIEvgIBADANBg" not in out
    assert "<redacted>" in out


def test_truncates_oversized_artifact():
    sec = _load_outbound()
    text = "ok " * 50_000
    out = sec.sanitize_remote_text(text, kind="artifact", max_chars=200)
    assert len(out) <= 200
    assert out.endswith("…[truncated]")


def test_stable_remote_error_codes():
    sec = _load_outbound()
    assert sec.stable_remote_error("not_in_allowlist") == "authorization_rejected"
    assert sec.stable_remote_error("tampered_metadata") == "authorization_rejected"
    assert sec.stable_remote_error("TimeoutError: boom") == "handler_timeout"
    assert sec.stable_remote_error("something else") == "task_failed"
