"""Incoming task queue, records, and worker loop for Hermes Agency nodes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .control_messages import handle_control_message

logger = logging.getLogger(__name__)

_INCOMING_ACTIVE_STATUSES = {"received", "queued", "processing"}
_INCOMING_TERMINAL_STATUSES = {"completed", "failed"}
_INCOMING_PERSISTENCE_MAX_RECORDS = 200


class RecoveredIncomingTask:
    """Minimal IncomingTask-compatible wrapper for tasks restored from disk."""

    def __init__(self, record: IncomingTaskRecord, node: Any) -> None:
        self._record = record
        self._node = node
        self.sender_card = record.sender_card
        self.metadata = dict(record.metadata)

    @property
    def task_id(self) -> str:
        return self._record.task_id

    @property
    def peer_id(self) -> str:
        return self._record.sender_peer_id

    @property
    def messages(self) -> list[Any]:
        return []

    @property
    def target_skill_id(self) -> str:
        return self._record.target_skill_id

    def _grpc(self) -> Any:
        grpc = getattr(self._node, "_grpc", None)
        if grpc is None:
            raise RuntimeError("Recovered task cannot update remote state without an active node")
        return grpc

    async def update_status(self, status: str) -> None:
        from agentanycast.node import _python_status_to_proto
        from agentanycast.task import TaskStatus

        await self._grpc().update_task_status(
            self.task_id,
            _python_status_to_proto(TaskStatus.from_value(status)),
        )

    async def complete(self, artifacts: list[dict[str, Any]] | None = None) -> None:
        from agentanycast.node import _artifact_to_proto
        from agentanycast.task import Artifact

        pb_artifacts = [
            _artifact_to_proto(item if isinstance(item, Artifact) else Artifact.from_dict(item))
            for item in (artifacts or [])
        ]
        await self._grpc().complete_task(self.task_id, pb_artifacts)

    async def fail(self, error: str) -> None:
        await self._grpc().fail_task(self.task_id, error)

    async def send_artifact(self, artifacts: list[dict[str, Any]]) -> None:
        # The current SDK IncomingTask surface does not expose progress-only
        # delivery. Keep recovered progress local instead of risking a terminal
        # CompleteTask update for an intermediate artifact.
        del artifacts


@dataclass
class IncomingTaskRecord:
    """Serializable local queue/registry record for an incoming A2A task."""

    task_id: str
    sender_peer_id: str
    sender_card: dict[str, Any] | None
    target_skill_id: str
    message_text: str
    context_id: str = ""
    context_packet: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    kanban_task_id: str | None = None
    progress_updates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "received"
    result_text: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "sender_peer_id": self.sender_peer_id,
            "sender_card": self.sender_card,
            "target_skill_id": self.target_skill_id,
            "message_text": self.message_text,
            "context_id": self.context_id,
            "context_packet": self.context_packet,
            "metadata": dict(self.metadata),
            "kanban_task_id": self.kanban_task_id,
            "progress_updates": list(self.progress_updates),
            "status": self.status,
            "result_text": self.result_text,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IncomingTaskRecord:
        metadata_raw = data.get("metadata")
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        progress_raw = data.get("progress_updates")
        progress = progress_raw if isinstance(progress_raw, list) else []
        completed_raw = data.get("completed_at")
        return cls(
            task_id=str(data.get("task_id") or ""),
            sender_peer_id=str(data.get("sender_peer_id") or ""),
            sender_card=data.get("sender_card")
            if isinstance(data.get("sender_card"), dict)
            else None,
            target_skill_id=str(data.get("target_skill_id") or ""),
            message_text=str(data.get("message_text") or ""),
            context_id=str(data.get("context_id") or ""),
            context_packet=data.get("context_packet")
            if isinstance(data.get("context_packet"), dict)
            else None,
            metadata={str(k): v for k, v in metadata.items()},
            kanban_task_id=str(data.get("kanban_task_id") or "") or None,
            progress_updates=[item for item in progress if isinstance(item, dict)],
            status=str(data.get("status") or "queued"),
            result_text=str(data.get("result_text"))
            if data.get("result_text") is not None
            else None,
            error=str(data.get("error")) if data.get("error") is not None else None,
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            completed_at=float(completed_raw) if completed_raw is not None else None,
        )


class IncomingQueueMixin:
    """Incoming task queue handling for :class:`node_manager.NodeManager`."""

    def _nm(self):
        """Return the defining node_manager module so test monkeypatches remain visible."""

        return sys.modules[self.__class__.__module__]

    @staticmethod
    def _message_text_from_incoming(task: Any) -> str:
        texts: list[str] = []
        for message in getattr(task, "messages", []) or []:
            for part in getattr(message, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text))
        return "\n".join(texts)

    def _sender_card_to_dict(self, task: Any) -> dict[str, Any] | None:
        sender_card = getattr(task, "sender_card", None)
        if sender_card is None:
            return None
        try:
            return self._nm().card_to_dict(sender_card)
        except Exception:
            return {
                "name": getattr(sender_card, "name", ""),
                "description": getattr(sender_card, "description", ""),
            }

    @staticmethod
    def _metadata_to_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items()}
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            try:
                data = value.to_dict()
                return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _kanban_task_id_from_metadata(
        metadata: dict[str, Any], context_packet: dict[str, Any] | None = None
    ) -> str | None:
        for key in ("kanban_task_id", "agency_kanban_task_id"):
            value = metadata.get(key)
            if value:
                return str(value)
        if context_packet:
            nested = context_packet.get("metadata")
            if isinstance(nested, dict):
                value = nested.get("kanban_task_id") or nested.get("agency_kanban_task_id")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _is_duplicate_working_transition(exc: Exception) -> bool:
        """Return True for idempotent incoming WORKING status updates.

        Some daemon builds may mark an inbound task WORKING before the Python
        handler gets its first chance to call ``IncomingTask.update_status``.
        Treating that as fatal converts an otherwise valid remote task into a
        FAILED task and breaks the completion return path.
        """

        text = str(exc)
        return "invalid transition" in text and "WORKING -> WORKING" in text

    @staticmethod
    def _is_terminal_completed_error(exc: Exception) -> bool:
        """Return True when completion already won the daemon state race."""

        text = str(exc)
        return "terminal state COMPLETED" in text

    @staticmethod
    def _incoming_persistence_path(cfg: Any) -> Path | None:
        path = getattr(cfg, "incoming_queue_persistence_path", None)
        return Path(path).expanduser() if path else None

    @staticmethod
    def _incoming_persistence_enabled(cfg: Any) -> bool:
        return bool(getattr(cfg, "incoming_persist_queue", False))

    def _incoming_queued_task_ids(self) -> set[str]:
        queued_ids = getattr(self, "_queued_incoming_task_ids", None)
        if queued_ids is None:
            queued_ids = set()
            self._queued_incoming_task_ids = queued_ids
        return queued_ids

    def _prune_incoming_records_for_persistence(self) -> None:
        """Keep persistent queue state bounded without dropping active tasks."""

        active_ids = [
            task_id
            for task_id in self._incoming_order
            if self._incoming_records.get(task_id)
            and self._incoming_records[task_id].status in _INCOMING_ACTIVE_STATUSES
        ]
        terminal_ids = [
            task_id
            for task_id in self._incoming_order
            if self._incoming_records.get(task_id)
            and self._incoming_records[task_id].status in _INCOMING_TERMINAL_STATUSES
        ]
        keep_terminal = max(0, _INCOMING_PERSISTENCE_MAX_RECORDS - len(active_ids))
        kept_terminal_ids = terminal_ids[-keep_terminal:] if keep_terminal else []
        keep_ids = set(active_ids + kept_terminal_ids)
        self._incoming_order = self._nm().deque(
            task_id for task_id in self._incoming_order if task_id in keep_ids
        )
        for task_id in list(self._incoming_records):
            if task_id not in keep_ids:
                self._incoming_records.pop(task_id, None)
                self._incoming_queued_task_ids().discard(task_id)

    def _persist_incoming_records(self) -> None:
        cfg = self._nm().get_config()
        if not self._incoming_persistence_enabled(cfg):
            return
        path = self._incoming_persistence_path(cfg)
        if path is None:
            return
        self._prune_incoming_records_for_persistence()
        records = [
            self._incoming_records[task_id].as_dict()
            for task_id in self._incoming_order
            if task_id in self._incoming_records
        ]
        payload = {"version": 1, "updated_at": time.time(), "records": records}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                tmp_name = fh.name
                json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except Exception as exc:
            if tmp_name:
                try:
                    Path(tmp_name).unlink(missing_ok=True)
                except Exception:
                    pass
            logger.warning("Hermes Agency failed to persist incoming queue: %s", exc)

    def _load_persisted_incoming_records(self) -> list[IncomingTaskRecord]:
        cfg = self._nm().get_config()
        if not self._incoming_persistence_enabled(cfg):
            return []
        path = self._incoming_persistence_path(cfg)
        if path is None or not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Hermes Agency ignored corrupt incoming queue state %s: %s", path, exc)
            return []
        raw_records = data.get("records") if isinstance(data, dict) else []
        if not isinstance(raw_records, list):
            return []
        records: list[IncomingTaskRecord] = []
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            try:
                record = IncomingTaskRecord.from_dict(item)
            except Exception:
                continue
            if record.task_id:
                records.append(record)
        return records

    def _requeue_persisted_incoming_tasks(self) -> int:
        if self._incoming_queue is None or self._node is None:
            return 0
        recovered = 0
        queued_ids = self._incoming_queued_task_ids()
        for record in self._load_persisted_incoming_records():
            self._incoming_records[record.task_id] = record
            if record.task_id not in self._incoming_order:
                self._incoming_order.append(record.task_id)
            if record.status not in _INCOMING_ACTIVE_STATUSES:
                continue
            record.metadata = dict(record.metadata)
            record.metadata["recovered"] = True
            record.metadata.setdefault("interrupted_status", record.status)
            record.status = "queued"
            record.updated_at = time.time()
            if self._incoming_queue.full():
                continue
            self._incoming_queue.put_nowait(
                (RecoveredIncomingTask(record, self._node), record.task_id)
            )
            queued_ids.add(record.task_id)
            recovered += 1
        self._refresh_incoming_state()
        self._persist_incoming_records()
        if recovered:
            logger.info("Hermes Agency recovered %s incoming task(s) from disk", recovered)
        return recovered

    def _queue_waiting_recovered_tasks(self) -> None:
        if self._incoming_queue is None or self._node is None:
            return
        queued_ids = self._incoming_queued_task_ids()
        for task_id in list(self._incoming_order):
            if self._incoming_queue.full():
                break
            if task_id in queued_ids:
                continue
            record = self._incoming_records.get(task_id)
            if record is None or record.status != "queued":
                continue
            if not record.metadata.get("recovered"):
                continue
            self._incoming_queue.put_nowait((RecoveredIncomingTask(record, self._node), task_id))
            queued_ids.add(task_id)

    def _mark_incoming_activity(self) -> None:
        self.state.last_incoming_activity_at = time.time()

    def _refresh_incoming_state(self) -> None:
        if self._incoming_queue is not None:
            queue_size = self._incoming_queue.qsize()
            max_size = (
                self._incoming_queue.maxsize or self._nm().get_config().incoming_max_queue_size
            )
        else:
            queue_size = 0
            max_size = self._nm().get_config().incoming_max_queue_size
        records = list(self._incoming_records.values())
        self.state.incoming_task_count = len(records)
        self.state.incoming_queue_size = queue_size
        self.state.incoming_queue_max_size = max_size
        self.state.incoming_processing_count = sum(
            1 for item in records if item.status == "processing"
        )
        self.state.incoming_completed_count = sum(
            1 for item in records if item.status == "completed"
        )
        self.state.incoming_failed_count = sum(1 for item in records if item.status == "failed")

    def _remember_incoming_record(self, record: IncomingTaskRecord) -> None:
        cfg = self._nm().get_config()
        self._incoming_records[record.task_id] = record
        self._incoming_order.append(record.task_id)
        while len(self._incoming_order) > cfg.incoming_queue_limit:
            old_task_id = self._incoming_order.popleft()
            self._incoming_records.pop(old_task_id, None)
        self._refresh_incoming_state()
        self._persist_incoming_records()

    async def _handle_incoming_task(self, task: Any) -> None:
        """Queue an incoming remote task and mark it working immediately."""

        message_text = self._message_text_from_incoming(task)
        cfg = self._nm().get_config()
        if await handle_control_message(self, task, message_text, cfg):
            return
        context_packet = self._nm().parse_context_packet(message_text)
        metadata = self._metadata_to_dict(getattr(task, "metadata", None))
        sender_card = self._sender_card_to_dict(task)
        security = self._nm().verify_incoming_sender(task, cfg, purpose="task")
        if not security.allowed:
            reason = security.reason or "incoming task rejected by Hermes Agency security policy"
            logger.warning(
                "Hermes Agency rejected incoming task from %s: %s",
                security.sender_peer_id or "unknown peer",
                reason,
            )
            try:
                await task.fail(reason)
            except Exception:
                logger.exception("Failed to mark rejected incoming task as failed")
            return
        sender_peer_id = security.sender_peer_id
        context_id = ""
        if context_packet:
            context_id = str(context_packet.get("context_id") or "").strip()
        if not context_id:
            context_id = str(metadata.get("context_id") or "").strip()
        if context_id:
            if context_packet is None:
                cfg = self._nm().get_config()
                local_history = self._conversation_threads.get(context_id, [])
                ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
                now = time.time()
                filtered_history = [
                    item
                    for item in local_history
                    if not ttl or now - float(item.get("created_at") or now) <= ttl
                ]
                context_text = self._nm().build_conversation_context(
                    context_id,
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                    local_history=filtered_history,
                )
                context_packet = {
                    "context_id": context_id,
                    "conversation_history": list(filtered_history) if context_text else [],
                }
            elif not context_packet.get("conversation_history"):
                cfg = self._nm().get_config()
                local_history = self._conversation_threads.get(context_id, [])
                ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
                now = time.time()
                filtered_history = [
                    item
                    for item in local_history
                    if not ttl or now - float(item.get("created_at") or now) <= ttl
                ]
                context_text = self._nm().build_conversation_context(
                    context_id,
                    max_turns=cfg.incoming_conversation_max_turns,
                    ttl=cfg.incoming_conversation_ttl,
                    local_history=filtered_history,
                )
                if context_text:
                    context_packet["conversation_history"] = list(filtered_history)
        kanban_task_id = self._kanban_task_id_from_metadata(metadata, context_packet)
        agency_board = self._ensure_agency_board(
            task_id=kanban_task_id or getattr(task, "task_id", "") or None,
            title=self._nm().packet_goal_or_text(message_text),
            agent_name=self._nm().current_profile_name(),
            metadata=metadata,
            context_packet=context_packet,
            direction="incoming",
        )
        if agency_board:
            metadata.setdefault("agency_board", agency_board)
            if context_packet is not None:
                nested_metadata = context_packet.setdefault("metadata", {})
                if isinstance(nested_metadata, dict):
                    nested_metadata.setdefault("agency_board", agency_board)
        self._mark_incoming_activity()
        record = IncomingTaskRecord(
            task_id=task.task_id,
            sender_peer_id=sender_peer_id,
            sender_card=sender_card,
            target_skill_id=getattr(task, "target_skill_id", ""),
            message_text=self._nm().packet_goal_or_text(message_text),
            context_id=context_id,
            context_packet=context_packet,
            metadata=metadata,
            kanban_task_id=kanban_task_id,
        )
        self._remember_incoming_record(record)
        if not kanban_task_id:
            incoming_kanban = self._call_on_agency_board(
                agency_board,
                self._nm().kanban_track_delegation,
                message=record.message_text,
                assigned_to=self._nm().current_profile_name(),
                skills=[record.target_skill_id] if record.target_skill_id else [],
                a2a_task_id=record.task_id,
                metadata={
                    "direction": "incoming",
                    "agency_board": agency_board or "",
                    "sender_peer_id": record.sender_peer_id,
                    "receiver": self._nm().current_profile_name(),
                    "target_skill_id": record.target_skill_id,
                    "context_id": record.context_id,
                    "message": record.message_text,
                },
                description=message_text,
            )
            if incoming_kanban.get("available") and incoming_kanban.get("task_id"):
                kanban_task_id = str(incoming_kanban["task_id"])
                record.kanban_task_id = kanban_task_id
        if kanban_task_id:
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
                f"A2A task {record.task_id} received by {self._nm().current_profile_name()} and queued for work.",
            )
        if self._incoming_queue is None:
            record.status = "failed"
            record.error = "Incoming queue is not initialized"
            record.updated_at = time.time()
            record.completed_at = time.time()
            self._refresh_incoming_state()
            self._persist_incoming_records()
            try:
                await task.fail(record.error)
            except Exception:
                pass
            return
        if self._incoming_queue.full():
            self.state.incoming_dropped_count += 1
            record.status = "failed"
            record.error = (
                f"Incoming queue full ({self._incoming_queue.qsize()}/"
                f"{self._incoming_queue.maxsize}); task rejected"
            )
            record.updated_at = time.time()
            record.completed_at = time.time()
            if record.kanban_task_id:
                self._call_on_agency_board(
                    record.metadata.get("agency_board"),
                    self._nm().kanban_update_task,
                    record.kanban_task_id,
                    status="blocked",
                    error=record.error,
                )
            self._refresh_incoming_state()
            self._persist_incoming_records()
            logger.warning(
                "Hermes Agency incoming queue full; dropping newest task %s from %s "
                "(queue=%s/%s dropped=%s)",
                record.task_id,
                record.sender_peer_id or "unknown peer",
                self._incoming_queue.qsize(),
                self._incoming_queue.maxsize,
                self.state.incoming_dropped_count,
            )
            try:
                await task.fail(record.error)
            except Exception:
                pass
            return
        try:
            try:
                await task.update_status("working")
            except Exception as exc:
                if not self._is_duplicate_working_transition(exc):
                    raise
            record.status = "queued"
            record.updated_at = time.time()
            self._incoming_queue.put_nowait((task, record.task_id))
            self._incoming_queued_task_ids().add(record.task_id)
            self._refresh_incoming_state()
            self._persist_incoming_records()
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.updated_at = time.time()
            record.completed_at = time.time()
            if record.kanban_task_id:
                self._call_on_agency_board(
                    record.metadata.get("agency_board"),
                    self._nm().kanban_update_task,
                    record.kanban_task_id,
                    status="blocked",
                    error=record.error,
                )
            self._refresh_incoming_state()
            self._persist_incoming_records()
            try:
                await task.fail(record.error)
            except Exception:
                pass

    def _safe_stub_response(self, record: IncomingTaskRecord) -> str:
        cfg = self._nm().get_config()
        trusted = not cfg.trusted_peers or record.sender_peer_id in cfg.trusted_peers
        return (
            f"Hermes Agency safe stub on profile '{self.state.card_name or 'unknown'}' "
            f"received task {record.task_id} from {record.sender_peer_id or 'unknown peer'}.\n"
            f"Target skill: {record.target_skill_id or '(none)'}\n"
            f"Message:\n{record.message_text or '(empty)'}\n\n"
            "No Hermes tools, terminal commands, file edits, or live conversation injection were executed. "
            f"allow_remote_tasks={cfg.allow_remote_tasks}; trusted_peer={trusted}."
        )

    def _generate_response(self, record: IncomingTaskRecord) -> str:
        """Generate a conversational response based on the agent's profile."""
        card_name = self.state.card_name or "unknown"
        skill_count = self.state.skill_count

        # Build a response based on the message
        msg = record.message_text or ""
        response_parts = [
            f"Hi! I'm {card_name}, running as an Hermes Agency node on this machine.",
            f"I have {skill_count} skills installed.",
        ]

        # Try to answer common questions
        msg_lower = msg.lower()
        if "name" in msg_lower:
            response_parts.append(f"My name is {card_name}.")
        if "skill" in msg_lower:
            response_parts.append(f"I currently have {skill_count} skills available.")
        if "hear" in msg_lower or "there" in msg_lower:
            response_parts.append("Yes, I can hear you loud and clear! The P2P channel is working.")
        if "introduce" in msg_lower or "who are you" in msg_lower:
            response_parts.append(
                f"I'm {card_name}, an AI agent on a remote machine. "
                f"I talk to other agents via encrypted P2P relay."
            )

        return "\n".join(response_parts)

    async def _send_progress_update(self, task: Any, record: IncomingTaskRecord, text: str) -> None:
        message = str(text or "").strip()
        if not message:
            return
        timestamp = time.time()
        update = {"timestamp": timestamp, "text": message}
        record.progress_updates.append(update)
        record.updated_at = timestamp
        self._persist_incoming_records()
        artifact = {
            "artifact_id": f"progress-{record.task_id}-{len(record.progress_updates)}",
            "name": "agency-progress-update",
            "metadata": {"agency_progress": True, "timestamp": timestamp},
            "parts": [{"text": message}],
        }
        if not hasattr(task, "send_artifact"):
            return
        await task.send_artifact([artifact])

    def _progress_callback_for_task(self, task: Any, record: IncomingTaskRecord):
        loop = asyncio.get_running_loop()

        def callback(text: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._send_progress_update(task, record, text),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception:
                pass

        return callback

    def _remember_conversation_turn(self, record: IncomingTaskRecord, response: str) -> None:
        context_id = str(record.context_id or "").strip()
        if not context_id:
            return
        cfg = self._nm().get_config()
        thread = self._conversation_threads.setdefault(context_id, [])
        now = time.time()
        ttl = max(0, int(cfg.incoming_conversation_ttl or 0))
        if ttl:
            thread[:] = [
                item for item in thread if now - float(item.get("created_at") or now) <= ttl
            ]
        thread.append(
            {
                "task_id": record.task_id,
                "created_at": record.created_at,
                "user": record.message_text,
                "agent": response,
            }
        )
        max_turns = max(1, int(cfg.incoming_conversation_max_turns or 20))
        del thread[:-max_turns]

    async def _incoming_worker(self) -> None:
        """Process queued incoming tasks."""

        assert self._incoming_queue is not None
        while True:
            task, task_id = await self._incoming_queue.get()
            record = self._incoming_records.get(task_id)
            try:
                if record is None:
                    continue
                if record.metadata.get("recovered"):
                    try:
                        await task.update_status("working")
                    except Exception as exc:
                        if not self._is_duplicate_working_transition(exc):
                            raise
                record.status = "processing"
                record.updated_at = time.time()
                if record.kanban_task_id:
                    self._call_on_agency_board(
                        record.metadata.get("agency_board"),
                        self._nm().kanban_update_task,
                        record.kanban_task_id,
                        status="running",
                    )
                self._nm().announce_start(record.message_text)
                self._refresh_incoming_state()
                self._persist_incoming_records()
                cfg = self._nm().get_config()
                if not cfg.allow_remote_tasks:
                    response = self._safe_stub_response(record)
                elif cfg.incoming_mode in {"delegation", "subprocess"}:
                    try:
                        process_args = [record, cfg, self._generate_response]
                        process_kwargs = {}
                        if cfg.incoming_send_progress:
                            process_kwargs["progress_callback"] = self._progress_callback_for_task(
                                task,
                                record,
                            )
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._nm().process_incoming_task,
                                *process_args,
                                **process_kwargs,
                            ),
                            timeout=cfg.incoming_handler_timeout_seconds,
                        )
                    except TimeoutError as exc:
                        message = (
                            f"Handler timed out after {cfg.incoming_handler_timeout_seconds:g}s "
                            f"for task {record.task_id}"
                        )
                        logger.warning(
                            "Hermes Agency incoming handler timed out: handler=%s task_id=%s timeout=%ss",
                            cfg.incoming_mode,
                            record.task_id,
                            cfg.incoming_handler_timeout_seconds,
                        )
                        raise TimeoutError(message) from exc
                else:
                    response = self._generate_response(record)
                # The daemon can deliver the WORKING status update and the
                # subsequent completion on adjacent ticks. A very short yield
                # keeps the receiver-side state machine from racing a just-sent
                # status update, which otherwise intermittently marks the task
                # FAILED before CompleteTask is accepted in bidirectional flows.
                await asyncio.sleep(0.05)
                try:
                    await task.complete(
                        artifacts=[
                            {
                                "artifact_id": f"safe-stub-{record.task_id}",
                                "name": "agency-safe-stub-response",
                                "parts": [{"text": response}],
                            }
                        ]
                    )
                except Exception as exc:
                    if not self._is_terminal_completed_error(exc):
                        raise
                record.status = "completed"
                record.result_text = response
                record.updated_at = time.time()
                record.completed_at = time.time()
                self._persist_incoming_records()
                self._remember_conversation_turn(record, response)
                if record.kanban_task_id:
                    self._call_on_agency_board(
                        record.metadata.get("agency_board"),
                        self._nm().kanban_update_task,
                        record.kanban_task_id,
                        status="done",
                        result=response,
                    )
                    self._mark_agency_board_pending_review(
                        record.metadata.get("agency_board"),
                        task_id=record.kanban_task_id,
                        result=response,
                    )
                self._nm().announce_complete(
                    record.message_text, response, kanban_task_id=record.kanban_task_id
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if record is not None:
                    record.status = "failed"
                    record.error = f"{type(exc).__name__}: {exc}"
                    record.updated_at = time.time()
                    record.completed_at = time.time()
                    if record.kanban_task_id:
                        self._call_on_agency_board(
                            record.metadata.get("agency_board"),
                            self._nm().kanban_update_task,
                            record.kanban_task_id,
                            status="blocked",
                            error=record.error,
                        )
                    self._persist_incoming_records()
                    self._nm().announce_error(
                        record.message_text, record.error, kanban_task_id=record.kanban_task_id
                    )
                try:
                    await task.fail(
                        record.error if record is not None else f"{type(exc).__name__}: {exc}"
                    )
                except Exception:
                    pass
            finally:
                self._incoming_queued_task_ids().discard(task_id)
                self._mark_incoming_activity()
                self._incoming_queue.task_done()
                self._queue_waiting_recovered_tasks()
                self._refresh_incoming_state()
                self._persist_incoming_records()

    async def _incoming_tasks_impl(self, limit: int = 20) -> list[dict[str, Any]]:
        self._refresh_incoming_state()
        task_ids = list(self._incoming_order)[-max(1, limit) :]
        return [
            self._incoming_records[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._incoming_records
        ]
