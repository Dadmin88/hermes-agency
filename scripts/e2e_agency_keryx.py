#!/usr/bin/env python3
"""Prove a real Hermes Agency task round trip through Keryx processes.

The receiver uses Hermes Agency's production IncomingQueueMixin and safe-stub
execution path. The sender verifies the returned artifact while the receiver
persists evidence that trust, incoming lifecycle, Kanban completion, and pending
review reconciliation all ran.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import types
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "hermes-agency"
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from keryx.card import AgentCard, Skill  # noqa: E402
from keryx.node import KeryxNode  # noqa: E402
from keryx.task import Message, Part, TaskStatus  # noqa: E402

SKILL_ID = "agency.e2e.safe-stub"
SENDER_PEER = "agency-sender-peer"
RECEIVER_PEER = "agency-receiver-peer"
SENDER_TOKEN = "agency-sender-token-phase17"
RECEIVER_TOKEN = "agency-receiver-token-phase17"
KANBAN_TASK_ID = "agency-phase17-kanban"


def load_keryx_harness(keryx_root: Path):
    path = keryx_root / "scripts" / "e2e_two_node.py"
    spec = importlib.util.spec_from_file_location("agency_keryx_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Keryx harness from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_incoming_queue_module():
    package_name = "agency_e2e_plugin"
    package = types.ModuleType(package_name)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[package_name] = package

    control = types.ModuleType(f"{package_name}.control_messages")

    async def handle_control_message(*_args: Any, **_kwargs: Any) -> bool:
        return False

    control.handle_control_message = handle_control_message
    sys.modules[control.__name__] = control

    name = f"{package_name}.incoming_queue"
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / "incoming_queue.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Hermes Agency incoming queue")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class AgencyReceiverFactory:
    def __init__(self, evidence_path: Path) -> None:
        self.evidence_path = evidence_path
        self.module = load_incoming_queue_module()

    def create(self):
        module = self.module
        evidence_path = self.evidence_path

        class AgencyReceiver(module.IncomingQueueMixin):
            def __init__(self) -> None:
                self._incoming_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=8)
                self._incoming_records: dict[str, Any] = {}
                self._incoming_order = deque()
                self._queued_incoming_task_ids: set[str] = set()
                self._conversation_threads: dict[str, list[dict[str, Any]]] = {}
                self._node = None
                self.events: list[dict[str, Any]] = []
                self.state = SimpleNamespace(
                    card_name="Agency Receiver",
                    skill_count=1,
                    incoming_task_count=0,
                    incoming_queue_size=0,
                    incoming_queue_max_size=8,
                    incoming_dropped_count=0,
                    incoming_processing_count=0,
                    incoming_completed_count=0,
                    incoming_failed_count=0,
                    last_incoming_activity_at=None,
                )
                self.cfg = SimpleNamespace(
                    allow_remote_tasks=False,
                    trusted_peers={SENDER_PEER},
                    incoming_mode="safe-stub",
                    incoming_handler_timeout_seconds=10.0,
                    incoming_send_progress=False,
                    incoming_conversation_ttl=0,
                    incoming_conversation_max_turns=20,
                    incoming_max_queue_size=8,
                    incoming_queue_limit=50,
                    incoming_persist_queue=False,
                    incoming_queue_persistence_path=None,
                )
                self.facade = SimpleNamespace(
                    get_config=lambda: self.cfg,
                    parse_context_packet=lambda _text: None,
                    packet_goal_or_text=lambda text: text,
                    current_profile_name=lambda: "agency-receiver",
                    card_to_dict=lambda card: {
                        "name": getattr(card, "name", ""),
                        "description": getattr(card, "description", ""),
                    },
                    verify_incoming_sender=self.verify_sender,
                    kanban_track_delegation=self.track_delegation,
                    kanban_update_task=self.update_kanban,
                    kanban_add_comment=self.add_comment,
                    announce_start=lambda message: self.events.append(
                        {"event": "announce_start", "message": message}
                    ),
                    announce_complete=lambda message, result, **_kwargs: self.events.append(
                        {"event": "announce_complete", "message": message, "result": result}
                    ),
                    announce_error=lambda message, error, **_kwargs: self.events.append(
                        {"event": "announce_error", "message": message, "error": error}
                    ),
                    process_incoming_task=lambda *_args, **_kwargs: "unused",
                    deque=deque,
                )

            def _nm(self):
                return self.facade

            def _persist_incoming_records(self) -> None:
                return None

            def _ensure_agency_board(self, **_kwargs: Any) -> str:
                return "agency-e2e-board"

            def _call_on_agency_board(
                self,
                _board: Any,
                function: Any,
                *args: Any,
                **kwargs: Any,
            ) -> dict[str, Any]:
                result = function(*args, **kwargs)
                return result if isinstance(result, dict) else {"available": True}

            def _mark_agency_board_pending_review(
                self,
                _board: Any,
                *,
                task_id: str,
                result: str,
            ) -> None:
                self.events.append(
                    {"event": "pending_review", "task_id": task_id, "result": result}
                )

            def verify_sender(self, task: Any, _cfg: Any, *, purpose: str) -> Any:
                sender = str(getattr(task, "peer_id", "") or "")
                allowed = purpose == "task" and sender == SENDER_PEER
                self.events.append({"event": "trust", "sender_peer_id": sender, "allowed": allowed})
                return SimpleNamespace(
                    allowed=allowed,
                    sender_peer_id=sender,
                    reason="" if allowed else "unexpected authenticated sender",
                )

            def track_delegation(self, **kwargs: Any) -> dict[str, Any]:
                self.events.append({"event": "kanban_track", **kwargs})
                return {"available": True, "task_id": KANBAN_TASK_ID}

            def update_kanban(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
                self.events.append({"event": "kanban_update", "task_id": task_id, **kwargs})
                return {"available": True, "task_id": task_id}

            def add_comment(self, task_id: str, comment: str) -> dict[str, Any]:
                self.events.append(
                    {"event": "kanban_comment", "task_id": task_id, "comment": comment}
                )
                return {"available": True, "task_id": task_id}

            async def monitor(self) -> None:
                while True:
                    completed = [
                        record
                        for record in self._incoming_records.values()
                        if record.status in {"completed", "failed"}
                    ]
                    if completed:
                        record = completed[-1]
                        payload = {
                            "record": record.as_dict(),
                            "events": self.events,
                            "state": {
                                "incoming_completed_count": self.state.incoming_completed_count,
                                "incoming_failed_count": self.state.incoming_failed_count,
                            },
                        }
                        evidence_path.write_text(
                            json.dumps(payload, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        return
                    await asyncio.sleep(0.05)

        return AgencyReceiver()


async def run_worker(daemon_endpoint: str, evidence_path: Path) -> None:
    receiver = AgencyReceiverFactory(evidence_path).create()
    node = KeryxNode(
        AgentCard(
            name="Hermes Agency Receiver",
            description="Agency Phase 17 cross-process receiver",
            skills=[Skill(id=SKILL_ID, description="Hermes Agency safe-stub task")],
        ),
        daemon_endpoint=daemon_endpoint,
        worker_id="agency-phase17-worker",
        claim_wait_timeout_ms=250,
        heartbeat_interval_ms=500,
    )
    receiver._node = node

    @node.on_task
    async def on_task(task: Any) -> None:
        await receiver._handle_incoming_task(task)

    queue_worker = asyncio.create_task(receiver._incoming_worker())
    monitor = asyncio.create_task(receiver.monitor())
    await node.start()
    try:
        await node.serve_forever()
    finally:
        queue_worker.cancel()
        monitor.cancel()
        await node.stop()


async def wait_for_skill(node: KeryxNode, timeout: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        registrations = await node.discover(SKILL_ID, limit=10)
        if any(item.get("peer_id") == RECEIVER_PEER for item in registrations):
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("Hermes Agency receiver skill was not discoverable")


async def send_and_assert(sender_port: int, registry_port: int) -> None:
    node = KeryxNode(
        daemon_endpoint=f"127.0.0.1:{sender_port}",
        registry_endpoint=f"127.0.0.1:{registry_port}",
        worker_id="agency-phase17-sender",
    )
    await node.start()
    try:
        await wait_for_skill(node)
        print("PASS Agency specialist discovered")
        handle = await node.send_task(
            Message(parts=[Part(text="Produce the Agency Phase 17 safe-stub result")]),
            skill=SKILL_ID,
            metadata={
                "skill": SKILL_ID,
                "kanban_task_id": KANBAN_TASK_ID,
            },
        )
        result = await handle.wait(timeout=30)
        if result.status is not TaskStatus.COMPLETED:
            raise AssertionError(f"Agency task ended as {result.status.value}")
        text = "\n".join(
            part.text or "" for artifact in result.artifacts for part in artifact.parts if part.text
        )
        if "Hermes Agency safe stub" not in text:
            raise AssertionError(f"Agency result artifact was not returned: {text!r}")
        if SENDER_PEER not in text:
            raise AssertionError("Agency artifact did not preserve authenticated sender identity")
        print("PASS Agency terminal artifact returned")
    finally:
        await node.stop()


def relay_toml(work_dir: Path, relay_port: int, registry_port: int) -> Path:
    path = work_dir / "relay.toml"
    path.write_text(
        f'''[relay]
listen_addresses = ["tcp:0"]
bootstrap_peers = []
enable_mdns = false
max_circuits = 16
max_reservations = 16
max_reservations_per_peer = 4
connection_timeout_ms = 5000
use_ipv6 = false
health_grpc_bind = "127.0.0.1:{relay_port}"
health_http_bind = ""
registry_grpc_bind = "127.0.0.1:{registry_port}"

[[security.node_tokens]]
node_id = "{SENDER_PEER}"
token = "{SENDER_TOKEN}"

[[security.node_tokens]]
node_id = "{RECEIVER_PEER}"
token = "{RECEIVER_TOKEN}"
''',
        encoding="utf-8",
    )
    return path


def assert_receiver_evidence(path: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not path.exists():
        time.sleep(0.05)
    if not path.exists():
        raise AssertionError("Agency receiver did not write lifecycle evidence")
    payload = json.loads(path.read_text(encoding="utf-8"))
    record = payload["record"]
    events = payload["events"]
    if record["status"] != "completed":
        raise AssertionError(f"Agency incoming record was not completed: {record}")
    if record["sender_peer_id"] != SENDER_PEER:
        raise AssertionError(f"Agency trusted the wrong sender: {record}")
    statuses = [event.get("status") for event in events if event.get("event") == "kanban_update"]
    if "running" not in statuses or "done" not in statuses:
        raise AssertionError(f"Agency Kanban lifecycle incomplete: {statuses}")
    if not any(event.get("event") == "pending_review" for event in events):
        raise AssertionError("Agency did not mark the result pending review")
    if not any(event.get("event") == "trust" and event.get("allowed") is True for event in events):
        raise AssertionError("Agency trust check did not approve the authenticated sender")
    print("PASS Agency trust and incoming record verified")
    print("PASS Agency Kanban running to done verified")
    print("PASS Agency pending-review reconciliation verified")


def supervisor(args: argparse.Namespace) -> int:
    keryx_root = args.keryx_root.resolve()
    harness = load_keryx_harness(keryx_root)
    work_dir = (
        Path(tempfile.mkdtemp(prefix="agency-phase17-e2e-"))
        if args.work_dir is None
        else args.work_dir.resolve()
    )
    if args.work_dir is not None and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    group = harness.ProcessGroup(work_dir)
    success = False
    try:
        relay_port = harness.free_port()
        registry_port = harness.free_port()
        sender_port = harness.free_port()
        receiver_port = harness.free_port()
        bin_dir = keryx_root / "target" / "debug"
        relay_bin = harness.require_binary(bin_dir / "keryx-relay")
        daemon_bin = harness.require_binary(bin_dir / "keryxd")
        edge_bin = harness.require_binary(bin_dir / "keryx-node")

        relay_env = harness.base_env()
        relay_env["HERMES_KERYX_RELAY_CONFIG"] = str(
            relay_toml(work_dir, relay_port, registry_port)
        )
        group.start("relay", [str(relay_bin)], relay_env)
        harness.wait_tcp(relay_port, group)
        harness.wait_tcp(registry_port, group)
        print("PASS Agency relay and registry ready")

        sender_env = harness.daemon_env(
            peer_id=SENDER_PEER,
            data_dir=work_dir / "sender-data",
            daemon_port=sender_port,
            relay_port=relay_port,
            registry_port=registry_port,
        )
        receiver_env = harness.daemon_env(
            peer_id=RECEIVER_PEER,
            data_dir=work_dir / "receiver-data",
            daemon_port=receiver_port,
            relay_port=relay_port,
            registry_port=registry_port,
        )
        sender_env["HERMES_KERYX_NODE_TOKEN"] = SENDER_TOKEN
        receiver_env["HERMES_KERYX_NODE_TOKEN"] = RECEIVER_TOKEN
        group.start("sender-daemon", [str(daemon_bin)], sender_env)
        group.start("receiver-daemon", [str(daemon_bin)], receiver_env)
        harness.wait_tcp(sender_port, group)
        harness.wait_tcp(receiver_port, group)

        sender_edge_env = harness.edge_env(
            peer_id=SENDER_PEER,
            daemon_port=sender_port,
            relay_port=relay_port,
            registry_port=registry_port,
            key_path=work_dir / "sender-edge.key",
        )
        receiver_edge_env = harness.edge_env(
            peer_id=RECEIVER_PEER,
            daemon_port=receiver_port,
            relay_port=relay_port,
            registry_port=registry_port,
            key_path=work_dir / "receiver-edge.key",
            skills=SKILL_ID,
        )
        sender_edge_env["HERMES_KERYX_NODE_TOKEN"] = SENDER_TOKEN
        receiver_edge_env["HERMES_KERYX_NODE_TOKEN"] = RECEIVER_TOKEN
        group.start("sender-edge", [str(edge_bin)], sender_edge_env)
        group.start("receiver-edge", [str(edge_bin)], receiver_edge_env)

        evidence_path = work_dir / "agency-receiver-evidence.json"
        worker_env = harness.base_env()
        worker_env["PYTHONPATH"] = os.pathsep.join(
            [str(SRC_ROOT), worker_env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        group.start(
            "agency-receiver-worker",
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--daemon-endpoint",
                f"127.0.0.1:{receiver_port}",
                "--evidence-path",
                str(evidence_path),
            ],
            worker_env,
        )
        time.sleep(0.5)
        group.assert_alive()

        asyncio.run(send_and_assert(sender_port, registry_port))
        assert_receiver_evidence(evidence_path)
        success = True
        return 0
    except Exception as error:
        print(f"FAIL {type(error).__name__}: {error}", file=sys.stderr)
        group.print_tails()
        print(f"Preserved failure state: {work_dir}", file=sys.stderr)
        return 1
    finally:
        group.stop_all()
        if success and not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)
        elif success:
            print(f"Preserved successful state: {work_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keryx-root", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--daemon-endpoint", help=argparse.SUPPRESS)
    parser.add_argument("--evidence-path", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if not args.daemon_endpoint or args.evidence_path is None:
            raise SystemExit("worker mode requires daemon endpoint and evidence path")
        asyncio.run(run_worker(args.daemon_endpoint, args.evidence_path))
        return 0
    if args.keryx_root is None:
        raise SystemExit("--keryx-root is required")
    return supervisor(args)


if __name__ == "__main__":
    raise SystemExit(main())
