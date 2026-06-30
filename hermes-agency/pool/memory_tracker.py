#!/usr/bin/env python3
"""
Memory tracker for the Hermes Agency pool manager.

Reads RSS from /proc (Linux) — no external dependencies.
Tracks per-agent subprocess memory and system-wide availability.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_PAGESIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_SELF_STATM = Path("/proc/self/statm")
_MEMINFO = Path("/proc/meminfo")


def _read_rss_pages(statm_path: Path) -> int:
    """Read RSS pages from a /proc/<pid>/statm file.

    statm format: size resident shared text lib data dt (all in pages)
    Field index 1 = resident pages.
    """
    try:
        text = statm_path.read_text(encoding="utf-8").strip()
        fields = text.split()
        if len(fields) >= 2:
            return int(fields[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_meminfo() -> dict[str, int]:
    """Parse /proc/meminfo into a dict of field name -> kB value."""
    result: dict[str, int] = {}
    try:
        for line in _MEMINFO.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                result[key] = int(parts[1])
    except OSError:
        pass
    return result


class MemoryTracker:
    """Track memory usage for the pool manager process and its children."""

    def get_process_rss_mb(self) -> float:
        """Return current process RSS in MB."""
        pages = _read_rss_pages(_SELF_STATM)
        return (pages * _PAGESIZE) / (1024 * 1024)

    def get_child_rss_mb(self, pid: int) -> float:
        """Return child process RSS in MB. Returns 0.0 if process is gone."""
        statm = Path(f"/proc/{pid}/statm")
        pages = _read_rss_pages(statm)
        return (pages * _PAGESIZE) / (1024 * 1024)

    def get_system_available_mb(self) -> float:
        """Return available system memory in MB.

        Uses MemAvailable from /proc/meminfo (Linux 3.14+).
        Falls back to Free + Buffers + Cached if MemAvailable is missing.
        """
        info = _read_meminfo()
        avail_kb = info.get("MemAvailable")
        if avail_kb is not None:
            return avail_kb / 1024
        # Fallback for older kernels
        free = info.get("MemFree", 0)
        buffers = info.get("Buffers", 0)
        cached = info.get("Cached", 0)
        return (free + buffers + cached) / 1024

    def get_system_total_mb(self) -> float:
        """Return total system memory in MB."""
        info = _read_meminfo()
        return info.get("MemTotal", 0) / 1024

    def get_pool_memory_report(self, active: dict[str, Any]) -> dict[str, Any]:
        """Return per-agent and total memory stats.

        Args:
            active: PoolManager.active dict — name -> agent data with optional 'proc' key.
        """
        process_rss = self.get_process_rss_mb()
        system_avail = self.get_system_available_mb()
        system_total = self.get_system_total_mb()

        per_agent: dict[str, float] = {}
        for name, data in active.items():
            proc = data.get("proc")
            if proc is not None and hasattr(proc, "pid"):
                try:
                    per_agent[name] = round(self.get_child_rss_mb(proc.pid), 1)
                except (ProcessLookupError, OSError):
                    per_agent[name] = 0.0
            else:
                # CLI-managed agent (no direct proc handle)
                stored = data.get("rss_at_wake_mb")
                per_agent[name] = stored if stored is not None else 0.0

        return {
            "process_rss_mb": round(process_rss, 1),
            "system_available_mb": round(system_avail, 1),
            "system_total_mb": round(system_total, 1),
            "system_used_pct": round(
                ((system_total - system_avail) / system_total * 100) if system_total else 0, 1
            ),
            "per_agent_mb": per_agent,
            "agent_count": len(active),
        }
