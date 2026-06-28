"""Hermes Agency Hermes plugin.

Registers the ``agency`` toolset and lifecycle hooks for a per-profile
Hermes Agency node. The node auto-starts only when ``agency.auto_start`` is true,
or when this profile is the configured active orchestrator and
``agency.orchestrator.auto_start`` is explicitly enabled.
"""

from __future__ import annotations

# Pytest may import this file as a top-level module named ``__init__`` when the
# plugin directory is passed as a test path. In normal Hermes/plugin loading this
# module has a package context, so keep the real relative imports on that path and
# make top-level collection a harmless no-op.
if __package__:
    from .cli import handle_agency_slash, setup_agency_parser
    from .config import current_profile_name, get_config, is_current_orchestrator
    from .kanban_workspace import install_workspace_preservation_patch
    from .node_manager import manager
    from .orchestrator import ORCHESTRATOR_TOOLS, check_orchestrator_enabled
    from .tools import TOOLS, TOOLSET, check_agency_available

    def _stop_stale_pool_runner_for_in_process_node(cfg) -> None:
        """Prevent stale pool runners from racing the gateway-owned node.

        Gateway/desktop plugin startup hosts the active node in-process. A
        previous pool-managed ``agency_node_runner.py`` can survive restarts and
        keep handling A2A tasks with old bytecode, so stop matching runners
        before starting the in-process node.
        """

        should_start = cfg.auto_start or (
            is_current_orchestrator(cfg) and cfg.orchestrator.auto_start
        )
        if not (cfg.enabled and should_start):
            return
        try:
            from .pool.tools import stop_profile_runner_processes

            profile_name = current_profile_name()
            profile_dir = cfg.home.parent if cfg.home else None
            stop_profile_runner_processes(profile_name, profile_dir=profile_dir)
        except Exception:
            return

    def _auto_start_hook(**_: object) -> None:
        """Start the node when auto-start or active orchestrator role requires it."""

        _stop_stale_pool_runner_for_in_process_node(get_config())
        manager.auto_start_if_configured()

    def _team_context_hook(**_: object) -> dict[str, str] | None:
        """Inject cached team/orchestrator context through Hermes' plugin context path."""

        blocks = []
        team_context = manager.cached_team_context()
        if team_context:
            blocks.append(team_context)
        orchestrator_context = manager.cached_orchestrator_context()
        if orchestrator_context:
            blocks.append(orchestrator_context)
        if blocks:
            return {"context": "\n\n".join(blocks)}
        return None

    def _shutdown_hook(**_: object) -> None:
        """Stop the Hermes Agency node during an explicit session reset.

        Gateway sessions finalize after each Discord turn. Stopping the node on
        every finalize/end event tears down the libp2p swarm while remote A2A
        completions are still in flight, which makes the return path fail with
        `swarm closed`. Keep auto-started nodes alive for the process lifetime;
        explicit `/agency stop` or session reset can still stop them.
        """

        manager.stop_background()

    def register(ctx) -> None:
        """Register Hermes Agency tools and lifecycle hooks with Hermes."""

        ctx.register_cli_command(
            name="agency",
            help="Manage the Hermes Agency P2P node",
            setup_fn=setup_agency_parser,
            description="Start, stop, inspect, and discover peers via Hermes Agency.",
        )
        ctx.register_command(
            name="agency",
            handler=handle_agency_slash,
            description="Manage the Hermes Agency P2P node",
            args_hint="[status|start|stop|discover <skill>|doctor|setup-plugins|promote <agent>|demote <agent>|registry]",
        )

        cfg = get_config()
        if cfg.enabled:
            install_workspace_preservation_patch()
            for name, schema, handler, emoji in TOOLS:
                ctx.register_tool(
                    name=name,
                    toolset=TOOLSET,
                    schema=schema,
                    handler=handler,
                    check_fn=check_agency_available,
                    emoji=emoji,
                )

            if is_current_orchestrator(cfg):
                for name, schema, handler, emoji in ORCHESTRATOR_TOOLS:
                    ctx.register_tool(
                        name=name,
                        toolset=TOOLSET,
                        schema=schema,
                        handler=handler,
                        check_fn=check_orchestrator_enabled,
                        emoji=emoji,
                    )

        ctx.register_hook("on_session_start", _auto_start_hook)
        ctx.register_hook("on_session_start", _team_context_hook)
        ctx.register_hook("pre_llm_call", _team_context_hook)
        ctx.register_hook("on_session_reset", _shutdown_hook)

        # Discovery/load happens before hooks fire in many Hermes entry points. If
        # the operator enabled auto_start (or explicitly enabled orchestrator
        # auto_start), kick it once at registration so gateway/desktop launches can
        # bring the node up without waiting for a specific session-start event.
        # This remains non-blocking. Do not attempt startup when the optional SDK is
        # unavailable; plugin discovery must stay fail-open for profiles that have
        # the plugin present but dependencies absent.
        should_start = cfg.auto_start or (
            is_current_orchestrator(cfg) and cfg.orchestrator.auto_start
        )
        if cfg.enabled and check_agency_available() and should_start:
            _stop_stale_pool_runner_for_in_process_node(cfg)
            manager.start_background()
else:

    def register(ctx) -> None:  # pragma: no cover - only for pytest collection fallback
        raise RuntimeError("Hermes Agency plugin package was imported without a package context")
