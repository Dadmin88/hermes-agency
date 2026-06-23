"""Incoming task queue, records, and worker loop for Hermes Agency nodes."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from .control_messages import handle_control_message

logger = logging.getLogger(__name__)


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
            reason = security.reason
            try:
                await task.fail(reason)
            except Exception:
                pass
            logger.warning("Hermes Agency rejected incoming task: %s", reason)
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
            incoming_kanban = self._nm().kanban_track_delegation(
                message=record.message_text,
                assigned_to=self._nm().current_profile_name(),
                skills=[record.target_skill_id] if record.target_skill_id else [],
                a2a_task_id=record.task_id,
                metadata={
                    "direction": "incoming",
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
            self._nm().kanban_update_task(kanban_task_id, status="running")
            self._nm().kanban_add_comment(
                kanban_task_id,
                f"A2A task {record.task_id} received by {self._nm().current_profile_name()} and queued for work.",
            )
        if self._incoming_queue is None:
            record.status = "failed"
            record.error = "Incoming queue is not initialized"
            record.updated_at = time.time()
            record.completed_at = time.time()
            self._refresh_incoming_state()
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
                self._nm().kanban_update_task(
                    record.kanban_task_id, status="blocked", error=record.error
                )
            self._refresh_incoming_state()
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
            self._refresh_incoming_state()
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.updated_at = time.time()
            record.completed_at = time.time()
            if record.kanban_task_id:
                self._nm().kanban_update_task(
                    record.kanban_task_id, status="blocked", error=record.error
                )
            self._refresh_incoming_state()
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
                record.status = "processing"
                record.updated_at = time.time()
                if record.kanban_task_id:
                    self._nm().kanban_update_task(record.kanban_task_id, status="running")
                self._nm().announce_start(record.message_text)
                self._refresh_incoming_state()
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
                self._remember_conversation_turn(record, response)
                if record.kanban_task_id:
                    self._nm().kanban_update_task(
                        record.kanban_task_id, status="done", result=response
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
                        self._nm().kanban_update_task(
                            record.kanban_task_id, status="blocked", error=record.error
                        )
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
                self._incoming_queue.task_done()
                self._refresh_incoming_state()

    async def _incoming_tasks_impl(self, limit: int = 20) -> list[dict[str, Any]]:
        self._refresh_incoming_state()
        task_ids = list(self._incoming_order)[-max(1, limit) :]
        return [
            self._incoming_records[task_id].as_dict()
            for task_id in reversed(task_ids)
            if task_id in self._incoming_records
        ]
