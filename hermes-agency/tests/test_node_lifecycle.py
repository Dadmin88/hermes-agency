"""Regression coverage for NodeManager startup lifecycle coordination."""

from __future__ import annotations

import asyncio
import threading

import pytest

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


async def test_concurrent_stops_join_one_in_progress_teardown(node_manager_module, fake_keryx_sdk):
    """Concurrent stops share one teardown and both return the stopped state."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0

    async def refresh_team_context(*, force: bool = False) -> None:
        return None

    manager._refresh_team_context_impl = refresh_team_context
    node_cls = fake_keryx_sdk["KeryxNode"]
    original_stop = node_cls.stop
    teardown_entered = threading.Event()
    release_teardown = threading.Event()
    stop_calls = 0

    async def blocked_stop(self) -> None:
        nonlocal stop_calls
        stop_calls += 1
        teardown_entered.set()
        await asyncio.to_thread(release_teardown.wait)
        await original_stop(self)

    node_cls.stop = blocked_stop
    first_stop = None
    second_stop = None
    try:
        await manager._start_impl()

        first_stop = asyncio.create_task(manager._stop_impl())
        assert await asyncio.to_thread(teardown_entered.wait, 1)

        second_stop = asyncio.create_task(manager._stop_impl())
        await asyncio.sleep(0)
        assert not second_stop.done()

        release_teardown.set()
        first_state, second_state = await asyncio.gather(first_stop, second_stop)

        assert stop_calls == 1
        assert first_state is second_state is manager.state
        assert first_state.started is False
        assert second_state.started is False
        assert manager._node is None
    finally:
        release_teardown.set()
        if first_stop is not None:
            await asyncio.gather(first_stop, return_exceptions=True)
        if second_stop is not None:
            await asyncio.gather(second_stop, return_exceptions=True)
        await manager._stop_impl()


async def test_start_waits_for_stop_teardown_before_replacing_node(
    node_manager_module, fake_keryx_sdk
):
    """A start arriving during teardown must not reuse the still-stopping node."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0

    async def refresh_team_context(*, force: bool = False) -> None:
        return None

    manager._refresh_team_context_impl = refresh_team_context
    node_cls = fake_keryx_sdk["KeryxNode"]
    original_stop = node_cls.stop
    teardown_entered = threading.Event()
    release_teardown = threading.Event()

    async def blocked_stop(self) -> None:
        teardown_entered.set()
        await asyncio.to_thread(release_teardown.wait)
        await original_stop(self)

    node_cls.stop = blocked_stop
    stop_task = None
    start_task = None
    try:
        old_state = await manager._start_impl()
        old_node = node_cls.instances[0]
        assert old_state.started is True

        stop_task = asyncio.create_task(manager._stop_impl())
        assert await asyncio.to_thread(teardown_entered.wait, 1)

        start_task = asyncio.create_task(manager._start_impl())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(start_task), timeout=0.01)
        assert manager._node is old_node

        release_teardown.set()
        fresh_state = await start_task
        await stop_task

        assert len(node_cls.instances) == 2
        assert old_node.stopped is True
        assert fresh_state.started is True
        assert manager._node is node_cls.instances[1]
    finally:
        release_teardown.set()
        if start_task is not None:
            await asyncio.gather(start_task, return_exceptions=True)
        if stop_task is not None:
            await asyncio.gather(stop_task, return_exceptions=True)
        await manager._stop_impl()


async def test_fresh_start_retries_after_cancelled_startup_cleanup(
    node_manager_module, fake_keryx_sdk
):
    """A replacement start must drain a cancelled candidate before retrying."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
    startup_entered = threading.Event()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    node_cls = fake_keryx_sdk["KeryxNode"]
    original_start = node_cls.start
    original_stop = node_cls.stop
    first_candidate = None

    async def blocked_first_start(self) -> None:
        nonlocal first_candidate
        if first_candidate is None:
            first_candidate = self
            startup_entered.set()
            await asyncio.Future()
        await original_start(self)

    async def blocked_first_stop(self) -> None:
        if self is first_candidate:
            cleanup_entered.set()
            await asyncio.to_thread(release_cleanup.wait)
        await original_stop(self)

    node_cls.start = blocked_first_start
    node_cls.stop = blocked_first_stop
    first_start = asyncio.create_task(asyncio.to_thread(manager.start_sync, 0.01))
    replacement = None
    try:
        assert await asyncio.to_thread(startup_entered.wait, 1)
        assert await asyncio.to_thread(cleanup_entered.wait, 1)

        replacement = asyncio.create_task(asyncio.to_thread(manager.start_sync, 1))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(replacement), timeout=0.02)
        assert len(node_cls.instances) == 1

        release_cleanup.set()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(first_start, 1)
        state = await asyncio.wait_for(replacement, 1)

        assert state.started is True
        assert len(node_cls.instances) == 2
        assert first_candidate is not None and first_candidate.stopped is True
        assert manager._node is node_cls.instances[1]
        assert manager._startup_task is None
    finally:
        release_cleanup.set()
        pending = [first_start]
        if replacement is not None:
            pending.append(replacement)
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=2)
        finally:
            if manager._loop is not None:
                await asyncio.wait_for(asyncio.to_thread(manager.stop_sync, timeout=1), timeout=2)


async def test_timed_out_start_stops_constructed_unpublished_candidate(
    node_manager_module, fake_keryx_sdk
):
    """Cancelling the last startup owner stops its constructed candidate."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
    startup_entered = threading.Event()
    node_cls = fake_keryx_sdk["KeryxNode"]

    async def blocked_start(self) -> None:
        startup_entered.set()
        await asyncio.Future()

    node_cls.start = blocked_start
    try:
        start_call = asyncio.create_task(asyncio.to_thread(manager.start_sync, 0.01))
        assert await asyncio.to_thread(startup_entered.wait, 1)

        with pytest.raises(TimeoutError):
            await start_call

        assert len(node_cls.instances) == 1
        assert node_cls.instances[0].stopped is True
        assert manager._node is None
        assert manager.state.started is False
    finally:
        await manager._stop_impl()


async def test_timed_out_start_waits_for_candidate_cleanup_acknowledgement(
    node_manager_module, fake_keryx_sdk
):
    """A timeout is not reported while its cancelled candidate is still cleaning up."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
    startup_entered = threading.Event()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    node_cls = fake_keryx_sdk["KeryxNode"]
    original_stop = node_cls.stop

    async def blocked_start(self) -> None:
        startup_entered.set()
        await asyncio.Future()

    async def blocked_stop(self) -> None:
        cleanup_entered.set()
        await asyncio.to_thread(release_cleanup.wait)
        await original_stop(self)

    node_cls.start = blocked_start
    node_cls.stop = blocked_stop
    try:
        start_call = asyncio.create_task(asyncio.to_thread(manager.start_sync, 0.01))
        assert await asyncio.to_thread(startup_entered.wait, 1)
        assert await asyncio.to_thread(cleanup_entered.wait, 1)
        assert not start_call.done()

        release_cleanup.set()
        with pytest.raises(TimeoutError):
            await start_call
    finally:
        release_cleanup.set()
        await manager._stop_impl()


async def test_timed_out_start_stops_idle_lifecycle_loop(node_manager_module, fake_keryx_sdk):
    """The dedicated loop does not survive a cancelled start with no published node."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
    startup_entered = threading.Event()
    release_startup = threading.Event()
    node_cls = fake_keryx_sdk["KeryxNode"]

    async def blocked_start(self) -> None:
        startup_entered.set()
        await asyncio.to_thread(release_startup.wait)

    node_cls.start = blocked_start
    try:
        start_call = asyncio.create_task(asyncio.to_thread(manager.start_sync, 0.01))
        assert await asyncio.to_thread(startup_entered.wait, 1)
        with pytest.raises(TimeoutError):
            await start_call

        assert manager._node is None
        assert manager._loop is None
        assert manager._thread is None
    finally:
        release_startup.set()
        if manager._loop is not None:
            await asyncio.to_thread(manager.stop_sync)


async def test_timed_out_sync_waiter_does_not_cancel_background_start(
    node_manager_module, fake_keryx_sdk
):
    """A timeout abandons only its synchronous wait, not another startup owner."""

    manager = node_manager_module.NodeManager()
    manager._ensure_incoming_runtime = lambda cfg: None
    manager._requeue_persisted_incoming_tasks = lambda: 0
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
        manager.start_background()
        background_future = manager._start_future
        assert background_future is not None
        assert await asyncio.to_thread(startup_entered.wait, 1)

        with pytest.raises(TimeoutError):
            await asyncio.to_thread(manager.start_sync, 0.01)

        release_startup.set()
        state = await asyncio.wrap_future(background_future)
        assert state.started is True
        assert len(node_cls.instances) == 1
    finally:
        release_startup.set()
        if manager._loop is not None:
            await asyncio.to_thread(manager.stop_sync)


async def test_cancelled_secondary_stop_waiter_does_not_interrupt_owner(
    node_manager_module, fake_keryx_sdk
):
    """Cancelling a shielded joiner leaves the event-blocked owner running."""

    manager = node_manager_module.NodeManager()
    node_cls = fake_keryx_sdk["KeryxNode"]
    teardown_entered = asyncio.Event()
    release_teardown = asyncio.Event()
    stop_calls = 0

    async def blocked_stop(self) -> None:
        nonlocal stop_calls
        stop_calls += 1
        teardown_entered.set()
        await release_teardown.wait()
        self.stopped = True

    node_cls.stop = blocked_stop
    manager._node = node_cls(card=object(), home=None)
    manager.state.started = True
    owner = asyncio.create_task(manager._stop_impl())
    secondary = None
    try:
        await teardown_entered.wait()
        secondary = asyncio.create_task(manager._stop_impl())
        await asyncio.sleep(0)
        secondary.cancel()
        with pytest.raises(asyncio.CancelledError):
            await secondary
        assert not owner.done()

        release_teardown.set()
        await owner
        assert stop_calls == 1
        assert manager._stop_task is None
    finally:
        release_teardown.set()
        await asyncio.gather(owner, return_exceptions=True)
        if secondary is not None:
            await asyncio.gather(secondary, return_exceptions=True)


async def test_cancelled_stop_owner_clears_its_marker(node_manager_module, fake_keryx_sdk):
    """Cancellation of the event-blocked teardown owner cannot strand its marker."""

    manager = node_manager_module.NodeManager()
    node_cls = fake_keryx_sdk["KeryxNode"]
    teardown_entered = asyncio.Event()

    async def blocked_stop(self) -> None:
        teardown_entered.set()
        await asyncio.Future()

    node_cls.stop = blocked_stop
    manager._node = node_cls(card=object(), home=None)
    manager.state.started = True
    owner = asyncio.create_task(manager._stop_impl())
    try:
        await teardown_entered.wait()
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert manager._stop_task is None
    finally:
        await asyncio.gather(owner, return_exceptions=True)


async def test_stop_marker_clears_when_finalization_raises_base_exception(node_manager_module):
    """A forced finalization BaseException cannot retain teardown ownership."""

    class FinalizationFailure(BaseException):
        pass

    manager = node_manager_module.NodeManager()

    def fail_finalization() -> None:
        raise FinalizationFailure()

    manager._refresh_incoming_state = fail_finalization
    with pytest.raises(FinalizationFailure):
        await manager._stop_impl()
    assert manager._stop_task is None


async def test_stop_owner_reentry_is_rejected_without_false_completion(
    node_manager_module, fake_keryx_sdk
):
    """Reentry from active teardown fails fast while its real owner remains live."""

    manager = node_manager_module.NodeManager()
    node_cls = fake_keryx_sdk["KeryxNode"]
    reentry_attempted = asyncio.Event()
    release_teardown = asyncio.Event()
    reentry_error: BaseException | None = None

    async def reentrant_stop(self) -> None:
        nonlocal reentry_error
        try:
            await manager._stop_impl()
        except BaseException as exc:
            reentry_error = exc
        reentry_attempted.set()
        await release_teardown.wait()
        self.stopped = True

    node_cls.stop = reentrant_stop
    manager._node = node_cls(card=object(), home=None)
    manager.state.started = True
    owner = asyncio.create_task(manager._stop_impl())
    try:
        await reentry_attempted.wait()
        assert isinstance(reentry_error, RuntimeError)
        assert "already owns" in str(reentry_error)
        assert not owner.done()
        assert manager._stop_task is owner

        release_teardown.set()
        await owner
        assert manager._stop_task is None
    finally:
        release_teardown.set()
        await asyncio.gather(owner, return_exceptions=True)


def test_stop_sync_timeout_does_not_stop_loop_owned_by_active_teardown(node_manager_module):
    """A timed-out joiner cannot reset the loop while a separate owner is live."""

    class ActiveStop:
        def done(self) -> bool:
            return False

    class Loop:
        def __init__(self) -> None:
            self.stop_calls = 0

        def is_running(self) -> bool:
            return True

        def call_soon_threadsafe(self, callback) -> None:
            self.stop_calls += 1

    class Thread:
        def __init__(self) -> None:
            self.join_calls = 0

        def join(self, timeout: float) -> None:
            self.join_calls += 1

    manager = node_manager_module.NodeManager()
    loop = Loop()
    thread = Thread()
    manager._loop = loop
    manager._thread = thread
    manager._stop_task = ActiveStop()

    def timed_out_submit(coro, timeout):
        coro.close()
        raise TimeoutError()

    manager._submit = timed_out_submit
    try:
        with pytest.raises(TimeoutError):
            manager.stop_sync(timeout=0.01)
        assert loop.stop_calls == 0
        assert thread.join_calls == 0
        assert manager._loop is loop
        assert manager._thread is thread
    finally:
        manager._stop_task = None
        manager._loop = None
        manager._thread = None
