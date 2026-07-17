"""Disabled-by-default singleton reconciliation loop for skill governance."""

from __future__ import annotations

import fcntl
import threading
import time
from pathlib import Path
from typing import Any

from .service import SkillGovernanceControlPlane


class SkillGovernanceManager:
    def __init__(
        self,
        control_plane: SkillGovernanceControlPlane,
        *,
        enabled: bool,
        is_orchestrator: bool,
        poll_interval_seconds: int = 30,
    ):
        self.control_plane = control_plane
        self.enabled = enabled
        self.is_orchestrator = is_orchestrator
        self.poll_interval_seconds = max(5, poll_interval_seconds)
        self._lock_handle: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_scan: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_scan_at: float | None = None

    @property
    def lock_path(self) -> Path:
        return self.control_plane.paths.state_root / "reconciler.lock"

    def start_sync(self) -> bool:
        if not self.enabled or not self.is_orchestrator:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self.lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = self.lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        self._lock_handle = handle
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="agency-skill-governance", daemon=True
        )
        self._thread.start()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._last_scan = self.control_plane.scan()
                self._last_error = None
            except Exception as exc:  # fail closed; next full scan reconciles
                self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_scan_at = time.time()
            self._stop.wait(self.poll_interval_seconds)

    def stop_sync(self, timeout: float = 10) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
            self._thread = None
        if self._lock_handle:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "orchestrator": self.is_orchestrator,
            "running": bool(self._thread and self._thread.is_alive()),
            "lock_path": str(self.lock_path),
            "last_scan_at": self._last_scan_at,
            "last_scan": self._last_scan,
            "last_error": self._last_error,
        }
