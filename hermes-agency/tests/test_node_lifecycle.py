"""Regression coverage for NodeManager startup lifecycle coordination."""

from __future__ import annotations

import asyncio
import threading

pytest_plugins = ("test_keryx_transport",)


async def test_concurrent_starts_join_one_in_progress_transition(
    node_manager_module, fake_keryx_sdk
):
    """A second start arriving mid-startup must reuse the first node transition."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0

    async def refresh_team_context(*, force: bool = False) -> None:
        return None

    manager._refresh_team_context_impl = refresh_team_context

    startup_entered = threading.Event()
    release_startup = threading.Event()
    node_cls = fake_keryx_sdk["KeryxNode"]
    original_start = node_cls.start

    async def blocked_start(self) -> None:
        startup_entered.set()
        await asyncio.to_thread(release_startup.wait)
        await original_start(self)

    node_cls.start = blocked_start
    try:
        first_start = asyncio.create_task(manager._start_impl())
        assert await asyncio.to_thread(startup_entered.wait, 1)

        second_start = asyncio.create_task(manager._start_impl())
        await asyncio.sleep(0)
        release_startup.set()

        first_state, second_state = await asyncio.gather(first_start, second_start)

        assert len(node_cls.instances) == 1
        assert first_state is second_state
        assert first_state.started is True
        assert first_state.error is None
    finally:
        release_startup.set()
        await manager._stop_impl()
