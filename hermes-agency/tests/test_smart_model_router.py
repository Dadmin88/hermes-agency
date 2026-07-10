from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_agency_module(monkeypatch, module_name: str):
    package = sys.modules.get("hermes_plugin")
    if package is None:
        package = types.ModuleType("hermes_plugin")
        package.__path__ = [str(PLUGIN_DIR)]
        monkeypatch.setitem(sys.modules, "hermes_plugin", package)
    full_name = f"hermes_plugin.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / f"{module_name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, module)
    spec.loader.exec_module(module)
    return module


def _health(preflight_mod, ok=True, category="ok"):
    return preflight_mod.ProviderHealthResult(
        ok=ok,
        category=category,
        message=category,
        provider="test-provider",
        model="test-model",
    )


def test_default_uncertain_routes_to_gpt55(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    ctx = router.TaskRoutingContext(title="Investigate task")
    decision = router.route_task_model(ctx, preflight_fn=lambda p, m: _health(preflight))

    assert decision.provider == "openai-codex"
    assert decision.model == "gpt-5.5"
    assert decision.source == "default_safe"
    assert decision.model_override == "gpt-5.5 --provider openai-codex"


def test_architecture_security_release_review_and_destructive_tasks_escalate(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    cases = [
        "Architecture design for API boundary",
        "Security review for auth credentials",
        "Release rollback migration plan",
        "Code review approval signoff",
        "Delete and rewrite production config",
    ]
    for title in cases:
        decision = router.route_task_model(
            router.TaskRoutingContext(title=title, body="clear acceptance criteria"),
            preflight_fn=lambda p, m: _health(preflight),
        )
        assert decision.source == "escalation"
        assert decision.model == "gpt-5.5"
        assert decision.risk_tags


def test_ambiguous_requirements_and_repeated_failures_escalate(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    ambiguous = router.route_task_model(
        router.TaskRoutingContext(title="Implement fix", body=""),
        preflight_fn=lambda p, m: _health(preflight),
    )
    repeated = router.route_task_model(
        router.TaskRoutingContext(title="Format docs", body="docs/a.md typo", prior_failures=1),
        preflight_fn=lambda p, m: _health(preflight),
    )

    assert ambiguous.source == "escalation"
    assert "ambiguous_requirements" in ambiguous.risk_tags
    assert repeated.source == "escalation"
    assert "repeated_failure" in repeated.risk_tags


def test_low_risk_docs_typo_can_downgrade_when_confident_and_healthy(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")
    cfg = router.default_task_routing_config()
    cfg["tiers"]["light_docs"] = {
        "provider": "nous",
        "model": "xiaomi/mimo-v2.5",
        "reason": "cheap docs",
    }

    decision = router._route(
        router.TaskRoutingContext(title="Fix typo", body="Correct spelling in docs/readme.md"),
        cfg,
        lambda p, m: _health(preflight),
    )

    assert decision.source == "task_rule"
    assert decision.provider == "nous"
    assert decision.model == "xiaomi/mimo-v2.5"
    assert decision.matched_rules == ["docs_typo"]


def test_low_risk_rule_denied_by_security_tag_escalates(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    decision = router.route_task_model(
        router.TaskRoutingContext(
            title="Fix typo",
            body="Correct spelling in docs/security.md",
            labels=["security"],
        ),
        preflight_fn=lambda p, m: _health(preflight),
    )

    assert decision.source == "escalation"
    assert decision.model == "gpt-5.5"


def test_failed_downgrade_preflight_uses_safe_default(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")
    cfg = router.default_task_routing_config()
    cfg["tiers"]["light_docs"] = {"provider": "opencode-go", "model": "deepseek-v4-pro"}

    def pf(provider, model):
        if provider == "opencode-go":
            return _health(preflight, ok=False, category="quota_exhausted")
        return _health(preflight)

    decision = router._route(
        router.TaskRoutingContext(title="Fix typo", body="Correct spelling in docs/readme.md"),
        cfg,
        pf,
    )

    assert decision.source == "health_fallback"
    assert decision.fallback_used is True
    assert decision.provider == "openai-codex"


def test_failed_safe_default_preflight_blocks_dispatch(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")
    cfg = router.default_task_routing_config()
    cfg["tiers"]["light_docs"] = {"provider": "opencode-go", "model": "deepseek-v4-pro"}

    decision = router._route(
        router.TaskRoutingContext(title="Fix typo", body="Correct spelling in docs/readme.md"),
        cfg,
        lambda p, m: _health(preflight, ok=False, category="auth_failed"),
    )

    assert decision.source == "blocked"
    assert decision.block_reason and "provider-health" in decision.block_reason
    assert decision.model_override is None


def test_default_safe_preflight_failure_blocks_uncertain_dispatch(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    decision = router.route_task_model(
        router.TaskRoutingContext(title="Investigate task"),
        preflight_fn=lambda p, m: _health(preflight, ok=False, category="quota_exhausted"),
    )

    assert decision.source == "blocked"
    assert decision.provider == "openai-codex"
    assert decision.model == "gpt-5.5"
    assert decision.block_reason == (
        "provider-health: safe default openai-codex/gpt-5.5 failed preflight (quota_exhausted)"
    )
    assert decision.model_override is None
    assert decision.preflight["category"] == "quota_exhausted"


def test_safe_default_preflight_failure_blocks_escalation_dispatch(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    decision = router.route_task_model(
        router.TaskRoutingContext(
            title="Security review",
            body="clear acceptance criteria",
        ),
        preflight_fn=lambda p, m: _health(preflight, ok=False, category="auth_failed"),
    )

    assert decision.source == "blocked"
    assert decision.block_reason == (
        "provider-health: safe default openai-codex/gpt-5.5 failed preflight (auth_failed)"
    )
    assert decision.model_override is None
    assert "security" in decision.risk_tags
    assert "provider_health" in decision.risk_tags


def test_safe_default_preflight_failure_blocks_when_router_disabled(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")
    cfg = router.default_task_routing_config()
    cfg["enabled"] = False

    decision = router._route(
        router.TaskRoutingContext(title="Fix typo", body="Correct spelling in docs/readme.md"),
        cfg,
        lambda p, m: _health(preflight, ok=False, category="provider_unavailable"),
    )

    assert decision.source == "blocked"
    assert decision.block_reason == (
        "provider-health: safe default openai-codex/gpt-5.5 failed preflight (provider_unavailable)"
    )
    assert decision.model_override is None
    assert "task routing disabled" in decision.reasons


def test_dispatch_passes_model_override_per_run_without_writing_profile_config(monkeypatch):
    _load_agency_module(monkeypatch, "provider_preflight")
    _load_agency_module(monkeypatch, "model_sets")
    routing = _load_agency_module(monkeypatch, "kanban_model_routing")

    calls = []

    class Task:
        id = "t_route"
        title = "Fix typo"
        body = "Correct spelling in docs/readme.md"
        assignee = "agency-docs-writer"
        skills = []
        priority = 0
        current_run_id = 7
        claim_lock = "lock"
        status = "running"
        model_override = None

    class Conn:
        def execute(self, *args):
            calls.append(args)
            return self

        def fetchone(self):
            return {"metadata": "{}"}

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Txn:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    def original(task, workspace, *, board=None):
        calls.append(("spawn", task.model_override, workspace, board))
        return 123

    fake_kb = types.SimpleNamespace(
        _default_spawn=original,
        connect_closing=lambda: Conn(),
        write_txn=lambda conn: Txn(),
        _append_event=lambda *args, **kwargs: calls.append(("event", args, kwargs)),
        parent_ids=lambda conn, task_id: [],
        child_ids=lambda conn, task_id: [],
        scoped_current_board=lambda board: Txn(),
    )
    hermes_cli = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", fake_kb)

    assert routing.install_task_model_router_patch() is True
    pid = fake_kb._default_spawn(Task(), "/tmp/work", board="agency")

    assert pid == 123
    assert ("spawn", "gpt-5.5 --provider openai-codex", "/tmp/work", "agency") in calls
    assert any(
        call[0] == "event" and call[1][2] == "model_routed"
        for call in calls
        if isinstance(call, tuple)
    )


def test_route_metadata_is_compact_and_secret_safe(monkeypatch):
    preflight = _load_agency_module(monkeypatch, "provider_preflight")
    router = _load_agency_module(monkeypatch, "smart_model_router")

    decision = router.route_task_model(
        router.TaskRoutingContext(
            title="Architecture design", body="secret_token=SHOULD_NOT_APPEAR"
        ),
        preflight_fn=lambda p, m: _health(preflight),
    )
    metadata = decision.metadata()[router.ROUTE_METADATA_KEY]

    assert metadata["provider"] == "openai-codex"
    assert metadata["model"] == "gpt-5.5"
    assert "secret_token" not in repr(metadata)
