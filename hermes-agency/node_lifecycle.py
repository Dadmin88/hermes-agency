"""Async event-loop and daemon lifecycle coordination for NodeManager."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Coroutine
from typing import Any


class NodeLifecycleMixin:
    """Dedicated loop plumbing and SDK node start/stop lifecycle."""

    def _loop_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._thread_lock:
            self._loop = loop
            self._thread_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._thread_ready.clear()
            self._thread = threading.Thread(
                target=self._loop_main,
                name="agency-node-loop",
                daemon=True,
            )
            self._thread.start()

        if not self._thread_ready.wait(timeout=10):
            raise RuntimeError("Timed out starting Hermes Agency lifecycle loop")
        assert self._loop is not None
        return self._loop

    def _submit(self, coro: Coroutine[Any, Any, Any], timeout: float = 120) -> Any:
        loop = self._ensure_loop()
        if threading.current_thread() is self._thread:
            raise RuntimeError("Cannot synchronously wait on the Hermes Agency loop thread")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _stop_loop_if_idle(self) -> None:
        with self._thread_lock:
            loop = self._loop
            thread = self._thread
            if loop is None or self.state.started:
                return
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)
        with self._thread_lock:
            self._loop = None
            self._thread = None
            self._thread_ready.clear()

    def _status_callback(self, message: str) -> None:
        self.state.last_status = message

    def _record_card_state(self, card: Any) -> None:
        data = self._nm().card_to_dict(card)
        self.state.card_name = data.get("name")
        self.state.skill_count = len(data.get("skills") or [])

    async def _ensure_started_impl(self) -> None:
        if self._node is None or not self.state.started:
            await self._start_impl()
        if self._node is None or not self.state.started:
            raise RuntimeError(self.state.error or "Hermes Agency node did not start")

    async def _start_impl(self) -> Any:
        if self._node is not None and self.state.started:
            return self.state

        cfg = self._nm().get_config()
        self.state.config = cfg
        self.state.error = None
        self.state.last_status = None

        if cfg.home:
            cfg.home.mkdir(parents=True, exist_ok=True)

        try:
            from agentanycast import Node

            card = self._nm().build_card()
            self._record_card_state(card)
            daemon_bin = self._nm()._resolve_daemon_bin()
            if daemon_bin is not None:
                self._status_callback(f"Using Hermes Agency daemon binary: {daemon_bin}")
            if cfg.relay_security.token:
                # Current protected daemon builds do not expose a token flag, but
                # exporting this keeps plugin configuration forward-compatible
                # with token-aware daemon builds without touching SDK source.
                os.environ["AGENTANYCAST_RELAY_TOKEN"] = cfg.relay_security.token
            node = Node(
                card=card,
                relay=cfg.relay,
                home=cfg.home,
                daemon_bin=daemon_bin,
                status_callback=self._status_callback,
            )
            node.on_task(self._handle_incoming_task)
            await node.start()

            self._node = node
            self.state.started = True
            self.state.peer_id = node.peer_id
            self.state.last_peer_id = node.peer_id
            self.state.did_key = self._peer_id_to_did_key(node.peer_id)
            self.state.started_at = time.time()
            self.state.stopped_at = None
            self.state.error = None

            self._incoming_queue = asyncio.Queue(maxsize=cfg.incoming_max_queue_size)
            self.state.incoming_queue_max_size = cfg.incoming_max_queue_size
            self._requeue_persisted_incoming_tasks()
            self._incoming_worker_task = asyncio.create_task(self._incoming_worker())
            self._serve_task = asyncio.create_task(node.serve_forever())
            self._serve_task.add_done_callback(self._serve_done)
            self.state.serve_task_running = True
            if cfg.team.auto_register:
                await self._nm().register_agent(node, card, current_load=self._current_load())
                registration_result = await self._register_skills_with_registries(card)
                self._handle_registry_registration_result(
                    registration_result,
                    retry_in_seconds=float(self._nm().REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS),
                )
                self._nm().announce_registration(
                    self.state.card_name or self._nm().current_profile_name(),
                    "registered",
                    peer_id=self.state.peer_id,
                )
            await self._refresh_team_context_impl(force=True)
            if cfg.team.auto_discover and self._team_refresh_task is None:
                self._team_refresh_task = asyncio.create_task(self._team_refresh_loop())
            if cfg.team.auto_register and self._registry_reregister_task is None:
                self.state.registry_reregister_loop_exited = False
                self._registry_reregister_task = asyncio.create_task(
                    self._registry_reregister_loop()
                )
                self._registry_reregister_task.add_done_callback(self._registry_reregister_done)
        except Exception as exc:
            self._node = None
            self._serve_task = None
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.error = f"{type(exc).__name__}: {exc}"
        return self.state

    async def _stop_impl(self) -> Any:
        try:
            if self._serve_task is not None and not self._serve_task.done():
                self._serve_task.cancel()
                await asyncio.gather(self._serve_task, return_exceptions=True)

            if self._incoming_worker_task is not None and not self._incoming_worker_task.done():
                self._incoming_worker_task.cancel()
                await asyncio.gather(self._incoming_worker_task, return_exceptions=True)

            if self._team_refresh_task is not None and not self._team_refresh_task.done():
                self._team_refresh_task.cancel()
                await asyncio.gather(self._team_refresh_task, return_exceptions=True)

            if (
                self._registry_reregister_task is not None
                and not self._registry_reregister_task.done()
            ):
                self._registry_reregister_task.cancel()
                await asyncio.gather(self._registry_reregister_task, return_exceptions=True)

            if self._node is not None:
                try:
                    if self._nm().get_config().team.auto_register:
                        await self._nm().deregister_agent(self._node, card=self._nm().build_card())
                        self._nm().announce_registration(
                            self.state.card_name or self._nm().current_profile_name(),
                            "deregistered",
                            peer_id=self.state.peer_id,
                        )
                except Exception:
                    pass
                await self._node.stop()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._serve_task = None
            self._incoming_worker_task = None
            self._team_refresh_task = None
            self._registry_reregister_task = None
            self._incoming_queue = None
            self._queued_incoming_task_ids.clear()
            self._node = None
            self._task_handles.clear()
            self.state.started = False
            self.state.peer_id = None
            self.state.serve_task_running = False
            self.state.next_retry_at = None
            self._refresh_registration_health()
            self.state.stopped_at = time.time()
            self._refresh_incoming_state()
        return self.state

    def _serve_done(self, task: asyncio.Task[None]) -> None:
        self.state.serve_task_running = False
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            self.state.error = f"serve_forever failed: {type(exc).__name__}: {exc}"

    @staticmethod
    def _peer_id_to_did_key(peer_id: str) -> str | None:
        try:
            from agentanycast import peer_id_to_did_key

            return peer_id_to_did_key(peer_id)
        except Exception:
            return None

    def start_sync(self, timeout: float = 120) -> Any:
        return self._submit(self._start_impl(), timeout=timeout)

    def stop_sync(self, timeout: float = 60) -> Any:
        try:
            return self._submit(self._stop_impl(), timeout=timeout)
        finally:
            self._stop_loop_if_idle()

    def start_background(self) -> None:
        """Kick off startup without blocking the caller.

        Used by plugin lifecycle hooks. If startup fails, ``state.error`` is
        populated by ``_background_start_done``.
        """

        if self.state.started or self._start_future is not None:
            return
        loop = self._ensure_loop()
        self._start_future = asyncio.run_coroutine_threadsafe(self._start_impl(), loop)
        self._start_future.add_done_callback(self._background_start_done)

    def stop_background(self) -> None:
        if not self.state.started and self._node is None:
            return
        try:
            self.stop_sync(timeout=60)
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def _background_start_done(self, future: Any) -> None:
        self._start_future = None
        try:
            future.result()
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"

    def auto_start_if_configured(self) -> None:
        cfg = self._nm().get_config()
        self.state.config = cfg
        if cfg.enabled and (cfg.auto_start or self._nm().is_current_orchestrator(cfg)):
            self.start_background()

    def _atexit_stop(self) -> None:
        self.stop_background()
