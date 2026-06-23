"""Outbound task Kanban tracking and status reconciliation."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any


class KanbanSyncMixin:
    """A2A send/status flows that reconcile SDK handles with Kanban state."""

    async def _send_task_impl(
        self,
        message: str,
        *,
        peer_id: str | None = None,
        skill: str | None = None,
        wait_seconds: float = 0,
        metadata: dict[str, str] | None = None,
        conversation_context: Any = None,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_started_impl()
        assert self._node is not None

        targets = sum(bool(item) for item in (peer_id, skill))
        if targets != 1:
            raise ValueError("Exactly one of peer_id or skill is required")

        cfg = self._nm().get_config()
        if peer_id:
            if not self._peer_allowed_by_effective_allowlist(cfg, peer_id):
                raise PermissionError(
                    f"target peer {peer_id} is not in effective agency.relay.allowlist"
                )
            self._nm().verify_peer_tofu(cfg, peer_id, source="outgoing_task")

        if isinstance(conversation_context, dict):
            packet_context = dict(conversation_context)
            if metadata:
                packet_context.setdefault("metadata", metadata)
        else:
            packet_context = {
                "summary": str(conversation_context or "").strip(),
                "metadata": metadata or {},
            }
        clean_context_id = str(context_id or packet_context.get("context_id") or "").strip()
        if clean_context_id:
            packet_context["context_id"] = clean_context_id
            packet_context.setdefault(
                "conversation_history",
                self._nm().build_conversation_history(
                    clean_context_id,
                    os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes"),
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                ),
            )
            metadata = dict(metadata or {})
            metadata.setdefault("context_id", clean_context_id)
        packet_context.setdefault("metadata", metadata or {})
        if clean_context_id:
            packet_context["metadata"].setdefault("context_id", clean_context_id)
            packet_context["metadata"].setdefault("message", message)
        packet_or_message = self._nm().build_context_packet(message, packet_context)
        message_text = self._nm().packet_to_message_text(packet_or_message)
        target_label = peer_id or skill or "unknown target"
        clean_metadata = {str(k): str(v) for k, v in (metadata or {}).items()} or None
        kanban_task_id = (clean_metadata or {}).get("kanban_task_id") or (clean_metadata or {}).get(
            "agency_kanban_task_id"
        )
        self._nm().announce_delegate(message, target_label, kanban_task_id=kanban_task_id)
        payload = {"role": "user", "parts": [{"text": message_text}]}
        if isinstance(packet_or_message, dict):
            clean_metadata = dict(clean_metadata or {})
            clean_metadata.setdefault("agency_context_packet", "v1")
        kanban_metadata = {
            **(dict(clean_metadata or {})),
            "target_peer_id": peer_id,
            "target_skill": skill,
            "sender": self._nm().current_profile_name(),
        }
        kanban_result = self._nm().kanban_track_delegation(
            message=message,
            assigned_to=peer_id or None,
            skills=[skill] if skill else [],
            a2a_task_id=None,
            kanban_task_id=kanban_task_id,
            metadata=kanban_metadata,
            description=message_text,
        )
        if kanban_result.get("available") and kanban_result.get("task_id"):
            kanban_task_id = str(kanban_result["task_id"])
        try:
            handle = await self._node.send_task(
                message=payload,
                peer_id=peer_id,
                skill=skill,
                metadata=clean_metadata,
            )
        except Exception as exc:
            send_error = f"{type(exc).__name__}: {exc}"
            if kanban_task_id:
                self._nm().kanban_update_task(kanban_task_id, status="blocked", error=send_error)
                self._nm().kanban_add_comment(
                    kanban_task_id, f"A2A task send failed before remote acceptance: {send_error}"
                )
            self._nm().announce_error(message, send_error, kanban_task_id=kanban_task_id)
            raise
        self._task_handles[handle.task_id] = handle
        kanban_result = self._nm().kanban_track_delegation(
            message=message,
            assigned_to=peer_id or None,
            skills=[skill] if skill else [],
            a2a_task_id=handle.task_id,
            kanban_task_id=kanban_task_id,
            metadata=kanban_metadata,
            description=message_text,
        )
        if kanban_result.get("available") and kanban_result.get("task_id"):
            kanban_task_id = str(kanban_result["task_id"])

        wait_error: str | None = None
        wait_started_at = time.time()
        if wait_seconds and wait_seconds > 0:
            try:
                await handle.wait(timeout=wait_seconds)
            except Exception as exc:
                # Timeout or remote failure should not erase the task handle;
                # callers can still poll a2a_status for the latest state.
                wait_error = f"{type(exc).__name__}: {exc}"
                if kanban_task_id:
                    self._nm().kanban_add_comment(
                        kanban_task_id, f"A2A wait returned before completion: {wait_error}"
                    )
                self._nm().announce_error(message, wait_error, kanban_task_id=kanban_task_id)

        data = self._serialize_handle(handle)
        if (
            wait_error
            and wait_seconds
            and peer_id
            and data.get("status") == "failed"
            and not data.get("artifact_text")
            and time.time() - wait_started_at < 2
        ):
            # A local daemon race can report an immediate artifact-free FAILED
            # state in bidirectional same-process flows even though a retry over
            # the same P2P return path succeeds milliseconds later. Retry once;
            # real remote work still surfaces as failed if the second attempt
            # fails or times out.
            await asyncio.sleep(0.5)
            handle = await self._node.send_task(
                message=payload,
                peer_id=peer_id,
                skill=skill,
                metadata=clean_metadata,
            )
            self._task_handles[handle.task_id] = handle
            kanban_result = self._nm().kanban_track_delegation(
                message=message,
                assigned_to=peer_id or None,
                skills=[skill] if skill else [],
                a2a_task_id=handle.task_id,
                kanban_task_id=kanban_task_id,
                metadata={
                    **(dict(clean_metadata or {})),
                    "target_peer_id": peer_id,
                    "target_skill": skill,
                    "sender": self._nm().current_profile_name(),
                    "retry_of": data.get("task_id"),
                },
                description=message_text,
            )
            wait_error = None
            try:
                await handle.wait(timeout=wait_seconds)
            except Exception as exc:
                wait_error = f"{type(exc).__name__}: {exc}"
                if kanban_task_id:
                    self._nm().kanban_add_comment(
                        kanban_task_id, f"A2A retry wait returned before completion: {wait_error}"
                    )
                self._nm().announce_error(message, wait_error, kanban_task_id=kanban_task_id)
            data = self._serialize_handle(handle)
        if not wait_error and wait_seconds and wait_seconds > 0:
            result_text = data.get("artifact_text") or data.get("status") or "completed"
            if kanban_task_id:
                self._nm().kanban_update_task(
                    kanban_task_id, status="done", result=str(result_text)
                )
            self._nm().announce_complete(message, result_text, kanban_task_id=kanban_task_id)
        elif wait_error:
            if kanban_task_id:
                self._nm().kanban_update_task(kanban_task_id, status="blocked", result=wait_error)
        elif kanban_task_id:
            self._nm().kanban_update_task(kanban_task_id, status="running")
            self._nm().kanban_add_comment(
                kanban_task_id, "A2A task sent, not waiting for completion"
            )
        if isinstance(packet_or_message, dict):
            data["context_packet"] = packet_or_message
        data["kanban"] = kanban_result
        data["announcements"] = self._nm().recent_announcements(limit=5)
        if wait_error:
            data["wait_error"] = wait_error
        return data

    async def _task_status_impl(self, task_id: str) -> dict[str, Any] | None:
        handle = self._task_handles.get(task_id)
        kanban = self._nm().kanban_get_task(task_id)
        if handle is None:
            if kanban.get("available") and kanban.get("ok"):
                task = kanban.get("task", {})
                return {
                    "task_id": task_id,
                    "status": task.get("plugin_status") or task.get("status"),
                    "kanban_status": task.get("plugin_status") or task.get("status"),
                    "kanban_task_id": kanban.get("task_id"),
                    "result": task.get("result"),
                    "kanban": kanban,
                }
            return None
        data = self._serialize_handle(handle)
        if kanban.get("available"):
            data["kanban"] = kanban
        if kanban.get("available") and kanban.get("ok"):
            task = kanban.get("task", {})
            kanban_task_id = kanban.get("task_id")
            kanban_status = task.get("plugin_status") or task.get("status")
            if (
                data.get("status") == "completed"
                and data.get("artifact_text")
                and kanban_task_id
                and kanban_status not in {"done", "blocked", "failed"}
            ):
                # Fire-and-forget sends return to the caller before the remote
                # artifact arrives, so _send_task_impl intentionally leaves the
                # outbound Kanban task running. The next explicit status poll is
                # the safe reconciliation point: if the SDK handle now contains
                # the completion artifact, close the Kanban task with that result
                # and re-read it so a2a_status reflects board truth.
                updated = self._nm().kanban_update_task(
                    str(kanban_task_id),
                    status="done",
                    result=str(data.get("artifact_text") or "completed"),
                )
                if updated.get("available") and updated.get("ok"):
                    kanban = self._nm().kanban_get_task(str(kanban_task_id))
                    data["kanban"] = kanban
                    task = kanban.get("task", {}) if kanban.get("ok") else task
                    kanban_status = task.get("plugin_status") or task.get("status")
            if kanban_status:
                data["kanban_status"] = kanban_status
                data["kanban_task_id"] = kanban_task_id
            if kanban_status in {"done", "blocked", "failed"} and data.get("status") not in {
                "failed",
                "cancelled",
            }:
                data["a2a_status"] = data.get("status")
                data["status"] = kanban_status
                if task.get("result") is not None:
                    data["result"] = task.get("result")
        return data
