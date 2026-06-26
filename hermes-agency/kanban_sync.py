"""Outbound task Kanban tracking and status reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Callable
from typing import Any

from .departments import (
    DEPARTMENT_BOARD_NAMES,
    DEPARTMENT_BOARD_SLUGS,
    get_department,
    get_department_board_slug,
)

_BOARD_FRAGMENT_RE = re.compile(r"[^a-z0-9_-]+")


class KanbanSyncMixin:
    """A2A send/status flows that reconcile SDK handles with Kanban state."""

    @staticmethod
    def _agency_board_fragment(value: Any, *, max_len: int = 48) -> str:
        text = str(value or "").strip().lower()
        text = _BOARD_FRAGMENT_RE.sub("-", text).strip("-_")
        text = re.sub(r"[-_]{2,}", "-", text)
        return text[:max_len].strip("-_")

    def _agency_board_slug(self, *, task_id: str | None = None, title: str | None = None) -> str:
        basis = str(task_id or title or "task").strip() or "task"
        fragment = self._agency_board_fragment(basis)
        digest = hashlib.sha1(basis.encode("utf-8", "ignore")).hexdigest()[:8]
        if not fragment:
            fragment = digest
        slug = f"agency-{fragment}"
        if len(slug) > 64:
            slug = f"{slug[:55].rstrip('-_')}-{digest}"
        return slug

    @staticmethod
    def _agency_board_from_metadata(
        metadata: dict[str, Any] | None, context_packet: dict[str, Any] | None = None
    ) -> str | None:
        for source in (metadata or {}, (context_packet or {}).get("metadata") or {}):
            if not isinstance(source, dict):
                continue
            for key in ("agency_board", "kanban_board", "board"):
                value = source.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _agent_from_metadata(
        metadata: dict[str, Any] | None, context_packet: dict[str, Any] | None = None
    ) -> str | None:
        for source in (metadata or {}, (context_packet or {}).get("metadata") or {}):
            if not isinstance(source, dict):
                continue
            for key in (
                "target_agent",
                "target_profile",
                "profile_name",
                "receiver",
                "assigned_to",
                "reviewer",
            ):
                value = source.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _department_board_slug(agent_name: str | None) -> str | None:
        """Return the department Kanban board slug for ``agent_name`` when known."""

        return get_department_board_slug(agent_name)

    @staticmethod
    def _ensure_all_department_boards(kb: Any) -> None:
        """Create the canonical department boards on first Kanban use."""

        for department, slug in DEPARTMENT_BOARD_SLUGS.items():
            if hasattr(kb, "board_exists") and kb.board_exists(slug):
                continue
            kb.create_board(
                slug,
                name=DEPARTMENT_BOARD_NAMES.get(department, f"Agency {department}"),
                description=(
                    "Hermes Agency department board. Status stays pending_review after task "
                    "completion until a human signs off."
                ),
            )

    def _ensure_agency_board(
        self,
        *,
        task_id: str | None = None,
        title: str | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        context_packet: dict[str, Any] | None = None,
        direction: str = "agency",
    ) -> str | None:
        """Create/mark an agency department Kanban board, failing open if unavailable."""

        cfg = self._nm().get_config()
        if not (cfg.enabled and cfg.team.kanban_integration):
            return None
        resolved_agent = agent_name or self._agent_from_metadata(metadata, context_packet)
        department = get_department(resolved_agent) or "Leadership"
        department_slug = (
            self._department_board_slug(resolved_agent) or DEPARTMENT_BOARD_SLUGS["Leadership"]
        )
        slug = department_slug
        display_title = " ".join(str(title or task_id or "Agency task").split()).strip()
        if len(display_title) > 96:
            display_title = display_title[:95].rstrip() + "…"
        board_name = (
            DEPARTMENT_BOARD_NAMES.get(department or "") or f"Agency: {display_title or slug}"
        )
        try:
            from hermes_cli import kanban_db as kb  # type: ignore

            if department_slug:
                self._ensure_all_department_boards(kb)
                meta = {"slug": slug, "name": board_name}
            elif hasattr(kb, "board_exists") and kb.board_exists(slug):
                meta = {"slug": slug, "name": board_name}
            else:
                meta = kb.create_board(
                    slug,
                    name=board_name,
                    description=(
                        "Hermes Agency department board. Status stays pending_review after task "
                        "completion until a human signs off."
                    ),
                )
            self._write_agency_board_metadata(
                kb,
                str(meta.get("slug") or slug),
                agency_status="active",
                direction=direction,
                source_task_id=task_id,
                source_title=display_title,
                target_agent=resolved_agent,
                department=department,
                human_signoff_required=True,
            )
            return str(meta.get("slug") or slug)
        except Exception:
            return None

    @staticmethod
    def _write_agency_board_metadata(kb: Any, slug: str, **fields: Any) -> dict[str, Any]:
        meta = kb.read_board_metadata(slug)
        meta.pop("db_path", None)
        meta.update({key: value for key, value in fields.items() if value is not None})
        meta.setdefault("created_at", int(time.time()))
        meta["updated_at"] = int(time.time())
        path = kb.board_metadata_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        meta["db_path"] = str(kb.kanban_db_path(slug))
        return meta

    def _call_on_agency_board(
        self, board_slug: str | None, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        if not board_slug:
            return fn(*args, **kwargs)
        try:
            from hermes_cli import kanban_db as kb  # type: ignore
        except Exception:
            return fn(*args, **kwargs)
        with kb.scoped_current_board(board_slug):
            return fn(*args, **kwargs)

    def _mark_agency_board_pending_review(
        self, board_slug: str | None, *, task_id: str | None = None, result: str | None = None
    ) -> None:
        if not board_slug:
            return
        try:
            from hermes_cli import kanban_db as kb  # type: ignore

            self._write_agency_board_metadata(
                kb,
                board_slug,
                agency_status="pending_review",
                pending_review_at=int(time.time()),
                completed_task_id=task_id,
                latest_result=str(result or "")[:4000] if result else None,
                human_signoff_required=True,
            )
        except Exception:
            return

    def sign_off_board_sync(
        self, board_slug: str, *, signed_off_by: str | None = None
    ) -> dict[str, Any]:
        """Mark an Agency board as human-signed-off without deleting it."""

        from hermes_cli import kanban_db as kb  # type: ignore

        clean_slug = self._agency_board_fragment(board_slug, max_len=64)
        if not clean_slug or not kb.board_exists(clean_slug):
            return {"ok": False, "error": f"board does not exist: {board_slug}"}
        meta = self._write_agency_board_metadata(
            kb,
            clean_slug,
            agency_status="signed_off",
            signed_off_at=int(time.time()),
            signed_off_by=signed_off_by or self._nm().current_profile_name(),
            human_signoff_required=False,
        )
        return {"ok": True, "board": meta}

    def cleanup_signed_off_boards_sync(
        self, *, older_than_days: int | None = None
    ) -> dict[str, Any]:
        """Archive signed-off Agency boards older than the configured age."""

        from hermes_cli import kanban_db as kb  # type: ignore

        cfg = self._nm().get_config()
        days = int(
            older_than_days if older_than_days is not None else cfg.kanban.board_cleanup_days
        )
        cutoff = int(time.time()) - max(0, days) * 86400
        archived: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for board in kb.list_boards(include_archived=False):
            slug = str(board.get("slug") or "")
            if slug == getattr(kb, "DEFAULT_BOARD", "default"):
                continue
            if slug in set(DEPARTMENT_BOARD_SLUGS.values()):
                skipped.append({"slug": slug, "reason": "department board"})
                continue
            if board.get("agency_status") != "signed_off":
                skipped.append({"slug": slug, "reason": "not signed_off"})
                continue
            signed_off_at = int(board.get("signed_off_at") or 0)
            if signed_off_at > cutoff:
                skipped.append({"slug": slug, "reason": "signed_off too recently"})
                continue
            archived.append(kb.remove_board(slug, archive=True))
        return {"ok": True, "older_than_days": days, "archived": archived, "skipped": skipped}

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
            packet_metadata = dict(packet_context.get("metadata") or {})
            packet_metadata.update(dict(metadata or {}))
            packet_context["metadata"] = packet_metadata
        else:
            packet_context = {
                "summary": str(conversation_context or "").strip(),
                "metadata": dict(metadata or {}),
            }
        clean_context_id = str(context_id or packet_context.get("context_id") or "").strip()
        clean_metadata = {str(k): str(v) for k, v in (packet_context.get("metadata") or {}).items()}
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
            clean_metadata.setdefault("context_id", clean_context_id)
        if clean_context_id:
            clean_metadata.setdefault("message", message)

        kanban_task_id = clean_metadata.get("kanban_task_id") or clean_metadata.get(
            "agency_kanban_task_id"
        )
        agency_board = self._ensure_agency_board(
            task_id=kanban_task_id or clean_context_id or None,
            title=message,
            agent_name=(
                clean_metadata.get("target_agent")
                or clean_metadata.get("target_profile")
                or clean_metadata.get("assigned_to")
                or peer_id
                or skill
            ),
            metadata=clean_metadata,
            context_packet=packet_context,
            direction="outgoing",
        )
        if agency_board:
            clean_metadata.setdefault("agency_board", agency_board)
            packet_context["agency_board"] = agency_board

        target_label = peer_id or skill or "unknown target"
        kanban_metadata = {
            **clean_metadata,
            "target_peer_id": peer_id,
            "target_skill": skill,
            "sender": self._nm().current_profile_name(),
        }
        kanban_result = self._call_on_agency_board(
            agency_board,
            self._nm().kanban_track_delegation,
            message=message,
            assigned_to=peer_id or None,
            skills=[skill] if skill else [],
            a2a_task_id=None,
            kanban_task_id=kanban_task_id,
            metadata=kanban_metadata,
            description=message,
        )
        if kanban_result.get("available") and kanban_result.get("task_id"):
            kanban_task_id = str(kanban_result["task_id"])
            clean_metadata.setdefault("kanban_task_id", kanban_task_id)
            clean_metadata.setdefault("agency_kanban_task_id", kanban_task_id)
            kanban_metadata["kanban_task_id"] = kanban_task_id
            kanban_metadata["agency_kanban_task_id"] = kanban_task_id
        packet_context["metadata"] = clean_metadata
        packet_or_message = self._nm().build_context_packet(message, packet_context)
        message_text = self._nm().packet_to_message_text(packet_or_message)
        self._nm().announce_delegate(message, target_label, kanban_task_id=kanban_task_id)
        payload = {"role": "user", "parts": [{"text": message_text}]}
        if isinstance(packet_or_message, dict):
            clean_metadata.setdefault("agency_context_packet", "v1")
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
                self._call_on_agency_board(
                    agency_board,
                    self._nm().kanban_update_task,
                    kanban_task_id,
                    status="blocked",
                    error=send_error,
                )
                self._call_on_agency_board(
                    agency_board,
                    self._nm().kanban_add_comment,
                    kanban_task_id,
                    f"A2A task send failed before remote acceptance: {send_error}",
                )
            self._nm().announce_error(message, send_error, kanban_task_id=kanban_task_id)
            raise
        self._task_handles[handle.task_id] = handle
        kanban_result = self._call_on_agency_board(
            agency_board,
            self._nm().kanban_track_delegation,
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
                    self._call_on_agency_board(
                        agency_board,
                        self._nm().kanban_add_comment,
                        kanban_task_id,
                        f"A2A wait returned before completion: {wait_error}",
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
            kanban_result = self._call_on_agency_board(
                agency_board,
                self._nm().kanban_track_delegation,
                message=message,
                assigned_to=peer_id or None,
                skills=[skill] if skill else [],
                a2a_task_id=handle.task_id,
                kanban_task_id=kanban_task_id,
                metadata={
                    **clean_metadata,
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
                    self._call_on_agency_board(
                        agency_board,
                        self._nm().kanban_add_comment,
                        kanban_task_id,
                        f"A2A retry wait returned before completion: {wait_error}",
                    )
                self._nm().announce_error(message, wait_error, kanban_task_id=kanban_task_id)
            data = self._serialize_handle(handle)
        if not wait_error and wait_seconds and wait_seconds > 0:
            result_text = data.get("artifact_text") or data.get("status") or "completed"
            if kanban_task_id:
                self._call_on_agency_board(
                    agency_board,
                    self._nm().kanban_update_task,
                    kanban_task_id,
                    status="done",
                    result=str(result_text),
                )
                self._mark_agency_board_pending_review(
                    agency_board, task_id=kanban_task_id, result=str(result_text)
                )
            self._nm().announce_complete(message, result_text, kanban_task_id=kanban_task_id)
        elif wait_error:
            if kanban_task_id:
                self._call_on_agency_board(
                    agency_board,
                    self._nm().kanban_update_task,
                    kanban_task_id,
                    status="blocked",
                    result=wait_error,
                )
        elif kanban_task_id:
            self._call_on_agency_board(
                agency_board,
                self._nm().kanban_update_task,
                kanban_task_id,
                status="running",
            )
            self._call_on_agency_board(
                agency_board,
                self._nm().kanban_add_comment,
                kanban_task_id,
                "A2A task sent, not waiting for completion",
            )
        if isinstance(packet_or_message, dict):
            data["context_packet"] = packet_or_message
        data["kanban"] = kanban_result
        if agency_board:
            data["agency_board"] = agency_board
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
        agency_board = self._agency_board_from_metadata(data.get("metadata") or {})
        if agency_board and not (kanban.get("available") and kanban.get("ok")):
            kanban = self._call_on_agency_board(agency_board, self._nm().kanban_get_task, task_id)
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
                updated = self._call_on_agency_board(
                    agency_board,
                    self._nm().kanban_update_task,
                    str(kanban_task_id),
                    status="done",
                    result=str(data.get("artifact_text") or "completed"),
                )
                self._mark_agency_board_pending_review(
                    agency_board,
                    task_id=str(kanban_task_id),
                    result=str(data.get("artifact_text") or "completed"),
                )
                if updated.get("available") and updated.get("ok"):
                    kanban = self._call_on_agency_board(
                        agency_board, self._nm().kanban_get_task, str(kanban_task_id)
                    )
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
