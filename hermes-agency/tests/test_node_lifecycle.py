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


async def test_stop_background_submits_teardown_while_startup_is_in_progress(
    node_manager_module,
):
    """A lifecycle-hook stop must not bypass an unpublished startup transition."""

    manager = node_manager_module.NodeManager()
    startup_gate = asyncio.Event()
    manager._startup_task = asyncio.create_task(startup_gate.wait())
    stop_calls: list[int] = []
    manager.stop_sync = lambda timeout: stop_calls.append(timeout)
    try:
        manager.stop_background()
        assert stop_calls == [60]
    finally:
        manager._startup_task.cancel()
        await asyncio.gather(manager._startup_task, return_exceptions=True)


async def test_stop_waits_for_blocked_startup_before_node_publication(
    node_manager_module, fake_keryx_sdk
):
    """Stop cannot return before an in-flight candidate node is stopped."""

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
    start_task = asyncio.create_task(manager._start_impl())
    stop_task = None
    try:
        assert await asyncio.to_thread(startup_entered.wait, 1)

        stop_task = asyncio.create_task(manager._stop_impl())
        await asyncio.sleep(0)
        assert not stop_task.done()

        release_startup.set()
        state = await stop_task
        await start_task

        node = node_cls.instances[0]
        assert node.stopped is True
        assert state.started is False
        assert manager.state.started is False
        assert manager._node is None
    finally:
        release_startup.set()
        await asyncio.gather(start_task, return_exceptions=True)
        if stop_task is not None:
            await asyncio.gather(stop_task, return_exceptions=True)
        await manager._stop_impl()
