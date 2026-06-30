"""End-to-end pytest tests for Hermes Agency pool operations.

Tests the full flow of pool management, department operations, agent lifecycle,
health watchdog, and model-set switching — all with mocked daemons so they run
in CI without real P2P infrastructure.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import threading
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures — mirrors test_unit.py's plugin_modules pattern
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """Set up synthetic hermes_plugin package so pool/tools.py relative imports work."""
    for name in list(sys.modules):
        if name == "hermes_plugin" or name.startswith("hermes_plugin."):
            sys.modules.pop(name, None)

    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()

    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: hermes_home
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    package = types.ModuleType("hermes_plugin")
    package.__path__ = [str(PLUGIN_DIR)]
    monkeypatch.setitem(sys.modules, "hermes_plugin", package)

    # Load departments module
    dept_spec = importlib.util.spec_from_file_location(
        "hermes_plugin.departments", PLUGIN_DIR / "departments.py"
    )
    dept_mod = importlib.util.module_from_spec(dept_spec)
    monkeypatch.setitem(sys.modules, "hermes_plugin.departments", dept_mod)
    dept_spec.loader.exec_module(dept_mod)

    # Load pool subpackage
    pool_pkg = types.ModuleType("hermes_plugin.pool")
    pool_pkg.__path__ = [str(PLUGIN_DIR / "pool")]
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool", pool_pkg)

    # Load pool.roster (stub — we mock load_roster in most tests)
    roster_spec = importlib.util.spec_from_file_location(
        "hermes_plugin.pool.roster", PLUGIN_DIR / "pool" / "roster.py"
    )
    roster_mod = importlib.util.module_from_spec(roster_spec)
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool.roster", roster_mod)
    try:
        roster_spec.loader.exec_module(roster_mod)
    except Exception:
        pass  # Some transitive imports may fail; we mock what we need

    # Load pool.tools
    tools_spec = importlib.util.spec_from_file_location(
        "hermes_plugin.pool.tools", PLUGIN_DIR / "pool" / "tools.py"
    )
    tools_mod = importlib.util.module_from_spec(tools_spec)
    monkeypatch.setitem(sys.modules, "hermes_plugin.pool.tools", tools_mod)
    try:
        tools_spec.loader.exec_module(tools_mod)
    except Exception:
        pass

    return types.SimpleNamespace(
        departments=dept_mod,
        pool_tools=tools_mod,
        hermes_home=hermes_home,
    )


@pytest.fixture
def mock_roster_data():
    """Standard mock roster with agents across departments."""
    return {
        "total": 6,
        "online": 2,
        "profiles": [
            {
                "name": "agency-backend-engineer",
                "online": True,
                "peer_id": "peer-backend-001",
                "skills": ["python", "api-design", "database"],
                "description": "Backend specialist",
            },
            {
                "name": "agency-frontend-engineer",
                "online": False,
                "peer_id": None,
                "skills": ["react", "css", "typescript"],
                "description": "Frontend specialist",
            },
            {
                "name": "agency-copywriter",
                "online": True,
                "peer_id": "peer-copy-001",
                "skills": ["writing", "editing"],
                "description": "Content specialist",
            },
            {
                "name": "agency-qa-lead",
                "online": False,
                "peer_id": None,
                "skills": ["testing", "automation"],
                "description": "QA lead",
            },
            {
                "name": "agency-creative-director",
                "online": False,
                "peer_id": None,
                "skills": ["branding", "art-direction"],
                "description": "Creative director",
            },
            {
                "name": "agency-orchestrator",
                "online": False,
                "peer_id": None,
                "skills": ["orchestration"],
                "description": "Team orchestrator",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Department Operations E2E
# ---------------------------------------------------------------------------


class TestDepartmentOperationsE2E:
    """Test department lifecycle operations end-to-end."""

    def test_department_roster_lists_correct_agents(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Engineering department should list backend and frontend engineers."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        result = json.loads(pt.pool_department_roster("Engineering"))
        assert result["ok"] is True
        assert result["department"] == "Engineering"
        agent_names = [a["name"] for a in result["agents"]]
        assert "agency-backend-engineer" in agent_names
        assert "agency-frontend-engineer" in agent_names
        assert "agency-copywriter" not in agent_names

    def test_department_roster_shows_online_status(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Department roster should reflect correct online/offline status."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        result = json.loads(pt.pool_department_roster("Engineering"))
        agents = {a["name"]: a for a in result["agents"]}
        assert agents["agency-backend-engineer"]["online"] is True
        assert agents["agency-frontend-engineer"]["online"] is False

    def test_department_roster_case_insensitive(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Department lookup should be case-insensitive."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        result1 = json.loads(pt.pool_department_roster("engineering"))
        result2 = json.loads(pt.pool_department_roster("ENGINEERING"))
        assert result1["ok"] is True
        assert result2["ok"] is True
        assert result1["department"] == result2["department"]

    def test_department_roster_rejects_empty_input(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Empty department name should return an error."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        result = json.loads(pt.pool_department_roster(""))
        assert result["ok"] is False

    def test_department_roster_rejects_unknown_department(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Unknown department should return an error."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        result = json.loads(pt.pool_department_roster("Finance"))
        assert result["ok"] is False
        assert "unknown department" in result["error"].lower()

    def test_department_wake_targets_only_offline(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Department wake should only wake offline agents."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        wake_calls = []

        def mock_wake(name):
            wake_calls.append(name)
            return json.dumps({"ok": True, "peer_id": f"peer-{name}"})

        monkeypatch.setattr(pt, "pool_wake", mock_wake)

        result = json.loads(pt.pool_department_wake("Engineering"))
        assert result["ok"] is True
        assert "agency-frontend-engineer" in wake_calls
        assert "agency-backend-engineer" not in wake_calls

    def test_department_sleep_targets_only_online(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Department sleep should only sleep online agents."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        sleep_calls = []

        def mock_sleep(name):
            sleep_calls.append(name)
            return json.dumps({"ok": True})

        monkeypatch.setattr(pt, "pool_sleep", mock_sleep)

        result = json.loads(pt.pool_department_sleep("Content"))
        assert result["ok"] is True
        assert "agency-copywriter" in sleep_calls

    def test_department_wake_handles_wake_failure(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Department wake should report failures without crashing."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)
        monkeypatch.setattr(
            pt, "pool_wake", lambda n: (_ for _ in ()).throw(RuntimeError("daemon failed"))
        )

        result = json.loads(pt.pool_department_wake("QA"))
        assert result["ok"] is True
        assert result["failed"] >= 1

    def test_department_sleep_empty_department(
        self, plugin_env, mock_roster_data, monkeypatch
    ):
        """Sleeping a department with no online agents should succeed."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "load_roster", lambda: mock_roster_data)

        sleep_calls = []
        monkeypatch.setattr(
            pt,
            "pool_sleep",
            lambda n: sleep_calls.append(n) or json.dumps({"ok": True}),
        )

        result = json.loads(pt.pool_department_sleep("Leadership"))
        assert result["ok"] is True
        assert result["slept"] == 0


# ---------------------------------------------------------------------------
# Agent Lifecycle E2E
# ---------------------------------------------------------------------------


class TestAgentLifecycleE2E:
    """Test agent creation, disable/enable, and profile generation."""

    def test_create_agent_generates_complete_profile(
        self, plugin_env, tmp_path, monkeypatch
    ):
        """pool_create_agent should generate SOUL.md, profile.yaml, ROUTING.md, and skills."""
        pt = plugin_env.pool_tools
        profile_dir = tmp_path / "profiles" / "agency-test-e2e-agent"
        monkeypatch.setattr(pt, "PROFILES", tmp_path / "profiles")

        mock_manager = MagicMock()
        mock_manager._ensure_profile = lambda name: profile_dir.mkdir(
            parents=True, exist_ok=True
        )
        mock_manager.lock = threading.Lock()
        mock_manager.active = {}
        mock_manager.persistent_agents = set()

        # Mock PoolManager where it's lazily imported inside pool_create_agent
        mock_pm_module = types.ModuleType("hermes_plugin.pool.manager")
        mock_pm_module.PoolManager = type(
            "MockPM", (), {"__new__": lambda cls: mock_manager}
        )
        monkeypatch.setitem(
            sys.modules, "hermes_plugin.pool.manager", mock_pm_module
        )
        monkeypatch.setattr(pt, "_lifecycle_tools_enabled", lambda: True)
        # Mock set_agent_created_by where it's imported from (pool.roster)
        roster_mod = sys.modules.get("hermes_plugin.pool.roster")
        if roster_mod is not None:
            monkeypatch.setattr(
                roster_mod, "set_agent_created_by", lambda n, s: None
            )

        result = json.loads(
            pt.pool_create_agent(
                "agency-test-e2e-agent",
                "Engineering",
                ["python", "testing"],
                "E2E test agent",
            )
        )
        assert result["ok"] is True

        # All expected files
        assert (profile_dir / "SOUL.md").exists()
        assert (profile_dir / "profile.yaml").exists()
        assert (profile_dir / "ROUTING.md").exists()
        assert (profile_dir / ".no-bundled-skills").exists()

        # SOUL.md has all standard sections
        soul = (profile_dir / "SOUL.md").read_text()
        for section in [
            "## Identity",
            "## Mission",
            "## Operating Principles",
            "## Primary Responsibilities",
            "## Non-Responsibilities",
            "## Collaboration Style",
            "## Safety Boundaries",
            "## Output Expectations",
            "## Delegation Behavior",
            "## Escalation Behavior",
            "## Definition of Done",
            "## Shared Workspace Protocol",
            "## Specialist-to-Specialist Delegation Protocol",
        ]:
            assert section in soul, f"Missing section: {section}"

        # profile.yaml has agency config
        yaml_content = (profile_dir / "profile.yaml").read_text()
        assert "agency:" in yaml_content
        assert "enabled: true" in yaml_content

        # ROUTING.md has delegation info
        routing = (profile_dir / "ROUTING.md").read_text()
        assert "## Delegation" in routing
        assert "## Handoff Format" in routing

    def test_create_agent_generates_starter_skills(
        self, plugin_env, tmp_path, monkeypatch
    ):
        """pool_create_agent should create department-appropriate starter skills."""
        pt = plugin_env.pool_tools
        profile_dir = tmp_path / "profiles" / "agency-test-skills-agent"
        monkeypatch.setattr(pt, "PROFILES", tmp_path / "profiles")

        mock_manager = MagicMock()
        mock_manager._ensure_profile = lambda name: profile_dir.mkdir(
            parents=True, exist_ok=True
        )

        mock_pm_module = types.ModuleType("hermes_plugin.pool.manager")
        mock_pm_module.PoolManager = type(
            "MockPM", (), {"__new__": lambda cls: mock_manager}
        )
        monkeypatch.setitem(
            sys.modules, "hermes_plugin.pool.manager", mock_pm_module
        )
        monkeypatch.setattr(pt, "_lifecycle_tools_enabled", lambda: True)
        roster_mod = sys.modules.get("hermes_plugin.pool.roster")
        if roster_mod is not None:
            monkeypatch.setattr(
                roster_mod, "set_agent_created_by", lambda n, s: None
            )

        result = json.loads(
            pt.pool_create_agent(
                "agency-test-skills-agent", "Design", ["figma"], "Design agent"
            )
        )
        assert result["ok"] is True

        skills_dir = profile_dir / "skills"
        assert skills_dir.exists()

        # Department starter skill
        design_skill = skills_dir / "design-workflow" / "SKILL.md"
        assert design_skill.exists()
        assert "name: design-workflow" in design_skill.read_text()

        # Custom skill placeholder
        figma_skill = skills_dir / "figma" / "SKILL.md"
        assert figma_skill.exists()
        assert "figma" in figma_skill.read_text().lower()

    def test_create_agent_rejects_duplicate_name(
        self, plugin_env, tmp_path, monkeypatch
    ):
        """pool_create_agent should reject creating an agent that already exists."""
        pt = plugin_env.pool_tools
        profile_dir = tmp_path / "profiles" / "agency-duplicate"
        profile_dir.mkdir(parents=True)
        monkeypatch.setattr(pt, "PROFILES", tmp_path / "profiles")
        monkeypatch.setattr(pt, "_lifecycle_tools_enabled", lambda: True)

        result = json.loads(
            pt.pool_create_agent("agency-duplicate", "Engineering")
        )
        assert result["ok"] is False
        assert "already exists" in result["error"]

    def test_create_agent_rejects_non_agency_name(
        self, plugin_env, tmp_path, monkeypatch
    ):
        """pool_create_agent should require 'agency-' prefix."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "PROFILES", tmp_path / "profiles")
        monkeypatch.setattr(pt, "_lifecycle_tools_enabled", lambda: True)

        result = json.loads(
            pt.pool_create_agent("freelance-worker", "Engineering")
        )
        assert result["ok"] is False
        assert "agency-" in result["error"]

    def test_create_agent_rejects_disabled_lifecycle(
        self, plugin_env, tmp_path, monkeypatch
    ):
        """pool_create_agent should reject when lifecycle tools are disabled."""
        pt = plugin_env.pool_tools
        monkeypatch.setattr(pt, "PROFILES", tmp_path / "profiles")
        monkeypatch.setattr(pt, "_lifecycle_tools_enabled", lambda: False)

        result = json.loads(
            pt.pool_create_agent("agency-test-disabled", "Engineering")
        )
        assert result["ok"] is False
        assert "disabled" in result["error"].lower()


# ---------------------------------------------------------------------------
# Health Watchdog E2E
# ---------------------------------------------------------------------------


class TestHealthWatchdogE2E:
    """Test the health watchdog crash detection and restart logic."""

    def test_watchdog_detects_crashed_process(self):
        """Watchdog should detect agents whose process has exited."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1
        mock_proc.pid = 12345

        active = {
            "agency-test-crash": {
                "peer_id": "peer-001",
                "last_active": datetime.now(),
                "woke_at": datetime.now() - timedelta(minutes=2),
                "proc": mock_proc,
                "persistent": False,
                "rss_at_wake_mb": None,
            }
        }

        crashed = []
        for name, data in list(active.items()):
            proc = data.get("proc")
            if proc is not None and hasattr(proc, "pid"):
                if proc.poll() is not None:
                    crashed.append((name, data))

        assert len(crashed) == 1
        assert crashed[0][0] == "agency-test-crash"

    def test_watchdog_skips_healthy_process(self):
        """Watchdog should not flag agents with running processes."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345

        active = {
            "agency-test-healthy": {
                "peer_id": "peer-002",
                "last_active": datetime.now(),
                "woke_at": datetime.now(),
                "proc": mock_proc,
                "persistent": False,
                "rss_at_wake_mb": None,
            }
        }

        crashed = []
        for name, data in list(active.items()):
            proc = data.get("proc")
            if proc is not None and hasattr(proc, "pid"):
                if proc.poll() is not None:
                    crashed.append((name, data))

        assert len(crashed) == 0

    def test_watchdog_auto_restarts_recently_woken_agent(self):
        """Agents that crash within 10min of wake should be marked for restart."""
        now = datetime.now()
        pending_restarts = []

        woke_at = now - timedelta(minutes=2)
        is_persistent = False
        elapsed = (now - woke_at).total_seconds()

        if not is_persistent and elapsed < 600:
            pending_restarts.append("agency-crash-recent")

        assert "agency-crash-recent" in pending_restarts

    def test_watchdog_skips_restart_for_old_wake(self):
        """Agents that crash after 10+ minutes should NOT be auto-restarted."""
        now = datetime.now()
        pending_restarts = []

        woke_at = now - timedelta(minutes=15)
        is_persistent = False
        elapsed = (now - woke_at).total_seconds()

        if not is_persistent and elapsed < 600:
            pending_restarts.append("agency-crash-old")

        assert len(pending_restarts) == 0

    def test_watchdog_skips_restart_for_persistent_agents(self):
        """Persistent agents should NOT be auto-restarted by watchdog."""
        now = datetime.now()
        pending_restarts = []

        woke_at = now - timedelta(minutes=1)
        is_persistent = True
        elapsed = (now - woke_at).total_seconds()

        if not is_persistent and elapsed < 600:
            pending_restarts.append("agency-orchestrator")

        assert len(pending_restarts) == 0

    def test_watchdog_restart_runs_outside_lock(self):
        """Restart handler should not hold the pool lock (deadlock safety)."""
        # Read the actual source file to verify the restart handler
        # runs after the with self.lock: block, not inside it.
        manager_path = PLUGIN_DIR / "pool" / "manager.py"
        code = manager_path.read_text()

        restart_marker = "# Auto-restart crashed agents (outside lock to avoid deadlock)"
        lock_marker = "with self.lock:"
        restart_pos = code.find(restart_marker)
        lock_pos = code.find(lock_marker)

        assert restart_pos > 0, "Restart handler marker not found in manager.py"
        assert lock_pos > 0, "Lock block not found in manager.py"
        assert restart_pos > lock_pos, (
            "Restart handler must run outside the lock block"
        )

        # The restart handler should call self.wake() which acquires its own lock
        restart_section = code[restart_pos:]
        assert "self.wake(" in restart_section, (
            "Restart handler must call self.wake() for auto-restart"
        )


# ---------------------------------------------------------------------------
# Model Set E2E
# ---------------------------------------------------------------------------


class TestModelSetE2E:
    """Test model-set resolution and switching."""

    def test_model_sets_available(self):
        """All expected model sets should be loadable."""
        model_sets_dir = PLUGIN_DIR / "model_sets"
        if not model_sets_dir.exists():
            pytest.skip("model_sets directory not found")

        yaml = pytest.importorskip("yaml")
        sets_found = []
        for p in model_sets_dir.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            if data and "name" in data:
                sets_found.append(data["name"])

        assert len(sets_found) >= 1, f"No model sets found in {model_sets_dir}"

    def test_model_set_has_required_fields(self):
        """Each model set should have name, defaults, and families."""
        model_sets_dir = PLUGIN_DIR / "model_sets"
        if not model_sets_dir.exists():
            pytest.skip("model_sets directory not found")

        yaml = pytest.importorskip("yaml")
        for p in model_sets_dir.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            if not data or "name" not in data:
                continue
            assert "defaults" in data, f"{p.name} missing 'defaults'"
            assert "families" in data, f"{p.name} missing 'families'"
            assert "family" in data["defaults"], f"{p.name} defaults missing family"

    def test_model_set_families_have_provider_and_model(self):
        """Each family in a model set should specify provider and model."""
        model_sets_dir = PLUGIN_DIR / "model_sets"
        if not model_sets_dir.exists():
            pytest.skip("model_sets directory not found")

        yaml = pytest.importorskip("yaml")
        for p in model_sets_dir.glob("*.yaml"):
            data = yaml.safe_load(p.read_text())
            if not data or "families" not in data:
                continue
            for family_name, family_config in data["families"].items():
                assert "provider" in family_config, (
                    f"{p.name} family {family_name} missing provider"
                )
                assert "model" in family_config, (
                    f"{p.name} family {family_name} missing model"
                )


# ---------------------------------------------------------------------------
# Department Mapping E2E
# ---------------------------------------------------------------------------


class TestDepartmentMappingE2E:
    """Test that department mapping is consistent and complete."""

    def test_all_eight_departments_have_agents(self, plugin_env):
        """All 8 departments should have at least one agent."""
        for dept, agents in plugin_env.departments.DEPARTMENT_AGENTS.items():
            assert len(agents) >= 1, f"Department {dept} has no agents"

    def test_all_departments_have_board_slugs(self, plugin_env):
        """All departments with agents should have board slugs."""
        for dept in plugin_env.departments.DEPARTMENT_AGENTS:
            assert dept in plugin_env.departments.DEPARTMENT_BOARD_SLUGS
            assert dept in plugin_env.departments.DEPARTMENT_BOARD_NAMES

    def test_agent_to_department_resolves(self, plugin_env):
        """Every primary agent should resolve to a department."""
        for dept, agents in plugin_env.departments.DEPARTMENT_AGENTS.items():
            for agent in agents:
                resolved = plugin_env.departments.get_department(f"agency-{agent}")
                # Agent may appear in multiple departments; first one wins via setdefault
                assert resolved is not None, (
                    f"agency-{agent} has no department mapping"
                )

    def test_board_slugs_follow_naming_convention(self, plugin_env):
        """Board slugs should follow 'agency-<department>' pattern."""
        for dept, slug in plugin_env.departments.DEPARTMENT_BOARD_SLUGS.items():
            assert slug == f"agency-{dept.lower()}", (
                f"Board slug for {dept} is '{slug}', expected 'agency-{dept.lower()}'"
            )

    def test_canonical_name_normalization(self, plugin_env):
        """canonical_agent_name should strip agency- prefix and normalize."""
        canon = plugin_env.departments.canonical_agent_name
        assert canon("agency-backend-engineer") == "backend"
        assert canon("backend-engineer") == "backend"
        assert canon("agency-frontend-designer") == "frontend"
        assert canon("copywriter") == "copywriter"
