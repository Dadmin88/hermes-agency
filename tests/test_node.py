"""Tests for Node and proto conversion functions — no daemon or gRPC required."""

from __future__ import annotations

import asyncio

import pytest

from agentanycast._generated.agentanycast.v1 import (
    a2a_models_pb2,
    agent_card_pb2,
)
from agentanycast.card import AgentCard, Skill
from agentanycast.node import (
    Node,
    _artifact_to_proto,
    _card_to_proto,
    _message_to_proto,
    _proto_artifact_to_python,
    _proto_card_to_python,
    _proto_message_to_python,
    _proto_status_to_python,
    _proto_task_to_python,
    _python_status_to_proto,
)
from agentanycast.task import Artifact, Message, Part, TaskStatus

# ── Status Mapping ───────────────────────────────────────────


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("proto_status", "expected"),
        [
            (a2a_models_pb2.TASK_STATUS_SUBMITTED, TaskStatus.SUBMITTED),
            (a2a_models_pb2.TASK_STATUS_WORKING, TaskStatus.WORKING),
            (a2a_models_pb2.TASK_STATUS_INPUT_REQUIRED, TaskStatus.INPUT_REQUIRED),
            (a2a_models_pb2.TASK_STATUS_COMPLETED, TaskStatus.COMPLETED),
            (a2a_models_pb2.TASK_STATUS_FAILED, TaskStatus.FAILED),
            (a2a_models_pb2.TASK_STATUS_CANCELED, TaskStatus.CANCELED),
            (a2a_models_pb2.TASK_STATUS_REJECTED, TaskStatus.REJECTED),
        ],
    )
    def test_proto_to_python(self, proto_status, expected):
        assert _proto_status_to_python(proto_status) == expected

    def test_proto_to_python_unknown_defaults_to_submitted(self):
        assert _proto_status_to_python(999) == TaskStatus.SUBMITTED

    @pytest.mark.parametrize(
        ("py_status", "expected"),
        [
            (TaskStatus.SUBMITTED, a2a_models_pb2.TASK_STATUS_SUBMITTED),
            (TaskStatus.WORKING, a2a_models_pb2.TASK_STATUS_WORKING),
            (TaskStatus.INPUT_REQUIRED, a2a_models_pb2.TASK_STATUS_INPUT_REQUIRED),
            (TaskStatus.COMPLETED, a2a_models_pb2.TASK_STATUS_COMPLETED),
            (TaskStatus.FAILED, a2a_models_pb2.TASK_STATUS_FAILED),
            (TaskStatus.CANCELED, a2a_models_pb2.TASK_STATUS_CANCELED),
            (TaskStatus.REJECTED, a2a_models_pb2.TASK_STATUS_REJECTED),
        ],
    )
    def test_python_to_proto(self, py_status, expected):
        assert _python_status_to_proto(py_status) == expected


# ── Card Conversion ──────────────────────────────────────────


class TestCardConversion:
    def test_card_to_proto_basic(self):
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            version="1.0.0",
            protocol_version="a2a/0.3",
        )
        pb = _card_to_proto(card)
        assert pb.name == "TestAgent"
        assert pb.description == "A test agent"
        assert pb.version == "1.0.0"
        assert pb.protocol_version == "a2a/0.3"
        assert len(pb.skills) == 0

    def test_card_to_proto_with_skills(self):
        card = AgentCard(
            name="Agent",
            skills=[
                Skill(id="s1", description="skill one", input_schema='{"type": "object"}'),
                Skill(id="s2", description="skill two", output_schema='{"type": "string"}'),
            ],
        )
        pb = _card_to_proto(card)
        assert len(pb.skills) == 2
        assert pb.skills[0].id == "s1"
        assert pb.skills[0].description == "skill one"
        assert pb.skills[0].input_schema == '{"type": "object"}'
        assert pb.skills[0].output_schema == ""
        assert pb.skills[1].id == "s2"
        assert pb.skills[1].output_schema == '{"type": "string"}'

    def test_card_to_proto_none_schemas_become_empty_string(self):
        card = AgentCard(
            name="Agent",
            skills=[Skill(id="s1", description="d")],
        )
        pb = _card_to_proto(card)
        assert pb.skills[0].input_schema == ""
        assert pb.skills[0].output_schema == ""

    def test_proto_card_to_python_basic(self):
        pb = agent_card_pb2.AgentCard(
            name="RemoteAgent",
            description="Remote",
            version="2.0.0",
            protocol_version="a2a/0.3",
        )
        card = _proto_card_to_python(pb)
        assert card.name == "RemoteAgent"
        assert card.description == "Remote"
        assert card.version == "2.0.0"
        assert len(card.skills) == 0

    def test_proto_card_to_python_with_skills(self):
        pb = agent_card_pb2.AgentCard(
            name="Agent",
            skills=[
                agent_card_pb2.Skill(
                    id="analyze",
                    description="Analyze data",
                    input_schema='{"type":"object"}',
                ),
            ],
        )
        card = _proto_card_to_python(pb)
        assert len(card.skills) == 1
        assert card.skills[0].id == "analyze"
        assert card.skills[0].input_schema == '{"type":"object"}'

    def test_proto_card_to_python_empty_schema_becomes_none(self):
        pb = agent_card_pb2.AgentCard(
            name="Agent",
            skills=[
                agent_card_pb2.Skill(id="s1", description="d", input_schema="", output_schema=""),
            ],
        )
        card = _proto_card_to_python(pb)
        assert card.skills[0].input_schema is None
        assert card.skills[0].output_schema is None

    def test_roundtrip_card(self):
        original = AgentCard(
            name="RoundTrip",
            description="Tests roundtrip",
            version="3.0.0",
            protocol_version="a2a/0.3",
            skills=[
                Skill(id="skill1", description="first"),
                Skill(id="skill2", description="second", input_schema="{}"),
            ],
        )
        pb = _card_to_proto(original)
        restored = _proto_card_to_python(pb)
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.version == original.version
        assert len(restored.skills) == 2
        assert restored.skills[0].id == "skill1"


# ── Message Conversion ───────────────────────────────────────


class TestMessageConversion:
    def test_message_to_proto_text_part(self):
        msg = Message(
            role="user",
            parts=[Part(text="Hello")],
            message_id="msg-1",
        )
        pb = _message_to_proto(msg)
        assert pb.message_id == "msg-1"
        assert pb.role == a2a_models_pb2.MESSAGE_ROLE_USER
        assert len(pb.parts) == 1
        assert pb.parts[0].text_part.text == "Hello"

    def test_message_to_proto_agent_role(self):
        msg = Message(role="agent", parts=[Part(text="Hi")])
        pb = _message_to_proto(msg)
        assert pb.role == a2a_models_pb2.MESSAGE_ROLE_AGENT

    def test_message_to_proto_url_part(self):
        msg = Message(role="user", parts=[Part(url="https://example.com")])
        pb = _message_to_proto(msg)
        assert pb.parts[0].url_part.url == "https://example.com"

    def test_message_to_proto_raw_part(self):
        msg = Message(role="user", parts=[Part(raw=b"\x01\x02\x03")])
        pb = _message_to_proto(msg)
        assert pb.parts[0].raw_part.data == b"\x01\x02\x03"

    def test_message_to_proto_with_media_type(self):
        msg = Message(role="user", parts=[Part(text="data", media_type="text/csv")])
        pb = _message_to_proto(msg)
        assert pb.parts[0].media_type == "text/csv"

    def test_message_to_proto_with_metadata(self):
        msg = Message(role="user", parts=[Part(text="hi", metadata={"key": "val"})])
        pb = _message_to_proto(msg)
        assert pb.parts[0].metadata["key"] == "val"

    def test_proto_message_to_python_text(self):
        pb = a2a_models_pb2.Message(
            message_id="m1",
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[
                a2a_models_pb2.Part(text_part=a2a_models_pb2.TextPart(text="Hello")),
            ],
        )
        msg = _proto_message_to_python(pb)
        assert msg.message_id == "m1"
        assert msg.role == "user"
        assert len(msg.parts) == 1
        assert msg.parts[0].text == "Hello"

    def test_proto_message_to_python_agent_role(self):
        pb = a2a_models_pb2.Message(
            role=a2a_models_pb2.MESSAGE_ROLE_AGENT,
            parts=[],
        )
        msg = _proto_message_to_python(pb)
        assert msg.role == "agent"

    def test_proto_message_to_python_url(self):
        pb = a2a_models_pb2.Message(
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[
                a2a_models_pb2.Part(url_part=a2a_models_pb2.UrlPart(url="https://x.com")),
            ],
        )
        msg = _proto_message_to_python(pb)
        assert msg.parts[0].url == "https://x.com"

    def test_proto_message_to_python_raw(self):
        pb = a2a_models_pb2.Message(
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[
                a2a_models_pb2.Part(raw_part=a2a_models_pb2.RawPart(data=b"\xab\xcd")),
            ],
        )
        msg = _proto_message_to_python(pb)
        assert msg.parts[0].raw == b"\xab\xcd"

    def test_proto_message_to_python_media_type(self):
        pb = a2a_models_pb2.Message(
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[
                a2a_models_pb2.Part(
                    text_part=a2a_models_pb2.TextPart(text="x"),
                    media_type="application/json",
                ),
            ],
        )
        msg = _proto_message_to_python(pb)
        assert msg.parts[0].media_type == "application/json"

    def test_proto_message_to_python_metadata(self):
        pb_part = a2a_models_pb2.Part(text_part=a2a_models_pb2.TextPart(text="x"))
        pb_part.metadata["foo"] = "bar"
        pb = a2a_models_pb2.Message(
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[pb_part],
        )
        msg = _proto_message_to_python(pb)
        assert msg.parts[0].metadata == {"foo": "bar"}

    def test_message_roundtrip(self):
        original = Message(
            role="user",
            parts=[
                Part(text="Question"),
                Part(url="https://example.com/data"),
            ],
            message_id="round-1",
        )
        pb = _message_to_proto(original)
        restored = _proto_message_to_python(pb)
        assert restored.role == original.role
        assert restored.message_id == original.message_id
        assert len(restored.parts) == 2
        assert restored.parts[0].text == "Question"
        assert restored.parts[1].url == "https://example.com/data"


# ── Artifact Conversion ──────────────────────────────────────


class TestArtifactConversion:
    def test_artifact_to_proto_text(self):
        art = Artifact(
            artifact_id="a1",
            name="result",
            parts=[Part(text="output data")],
        )
        pb = _artifact_to_proto(art)
        assert pb.artifact_id == "a1"
        assert pb.name == "result"
        assert len(pb.parts) == 1
        assert pb.parts[0].text_part.text == "output data"

    def test_artifact_to_proto_url(self):
        art = Artifact(parts=[Part(url="https://files.example.com/out.csv")])
        pb = _artifact_to_proto(art)
        assert pb.parts[0].url_part.url == "https://files.example.com/out.csv"

    def test_artifact_to_proto_raw(self):
        art = Artifact(parts=[Part(raw=b"\xff\xfe")])
        pb = _artifact_to_proto(art)
        assert pb.parts[0].raw_part.data == b"\xff\xfe"

    def test_proto_artifact_to_python_text(self):
        pb = a2a_models_pb2.Artifact(
            artifact_id="a2",
            name="chart",
            parts=[
                a2a_models_pb2.Part(text_part=a2a_models_pb2.TextPart(text="svg data")),
            ],
        )
        art = _proto_artifact_to_python(pb)
        assert art.artifact_id == "a2"
        assert art.name == "chart"
        assert art.parts[0].text == "svg data"

    def test_proto_artifact_to_python_url(self):
        pb = a2a_models_pb2.Artifact(
            parts=[
                a2a_models_pb2.Part(url_part=a2a_models_pb2.UrlPart(url="https://x.com/f")),
            ],
        )
        art = _proto_artifact_to_python(pb)
        assert art.parts[0].url == "https://x.com/f"

    def test_proto_artifact_to_python_raw(self):
        pb = a2a_models_pb2.Artifact(
            parts=[
                a2a_models_pb2.Part(raw_part=a2a_models_pb2.RawPart(data=b"\x00\x01")),
            ],
        )
        art = _proto_artifact_to_python(pb)
        assert art.parts[0].raw == b"\x00\x01"

    def test_artifact_roundtrip(self):
        original = Artifact(
            artifact_id="round",
            name="roundtrip",
            parts=[Part(text="hello"), Part(url="https://x.com")],
        )
        pb = _artifact_to_proto(original)
        restored = _proto_artifact_to_python(pb)
        assert restored.artifact_id == original.artifact_id
        assert restored.name == original.name
        assert len(restored.parts) == 2
        assert restored.parts[0].text == "hello"
        assert restored.parts[1].url == "https://x.com"

    def test_artifact_to_proto_multiple_parts(self):
        art = Artifact(
            parts=[
                Part(text="text"),
                Part(url="https://example.com"),
                Part(raw=b"\x01"),
            ],
        )
        pb = _artifact_to_proto(art)
        assert len(pb.parts) == 3


# ── Task Conversion ──────────────────────────────────────────


class TestTaskConversion:
    def test_proto_task_to_python(self):
        pb_msg = a2a_models_pb2.Message(
            message_id="m1",
            role=a2a_models_pb2.MESSAGE_ROLE_USER,
            parts=[a2a_models_pb2.Part(text_part=a2a_models_pb2.TextPart(text="Q"))],
        )
        pb_art = a2a_models_pb2.Artifact(
            artifact_id="a1",
            name="result",
            parts=[a2a_models_pb2.Part(text_part=a2a_models_pb2.TextPart(text="A"))],
        )
        pb_task = a2a_models_pb2.Task(
            task_id="t1",
            context_id="ctx-1",
            status=a2a_models_pb2.TASK_STATUS_COMPLETED,
            messages=[pb_msg],
            artifacts=[pb_art],
            target_skill_id="analyze",
            originator_peer_id="12D3KooWPeer",
        )
        task = _proto_task_to_python(pb_task)
        assert task.task_id == "t1"
        assert task.context_id == "ctx-1"
        assert task.status == TaskStatus.COMPLETED
        assert len(task.messages) == 1
        assert task.messages[0].parts[0].text == "Q"
        assert len(task.artifacts) == 1
        assert task.artifacts[0].name == "result"
        assert task.target_skill_id == "analyze"
        assert task.originator_peer_id == "12D3KooWPeer"

    def test_proto_task_empty_messages_and_artifacts(self):
        pb_task = a2a_models_pb2.Task(
            task_id="t2",
            status=a2a_models_pb2.TASK_STATUS_SUBMITTED,
        )
        task = _proto_task_to_python(pb_task)
        assert task.task_id == "t2"
        assert task.status == TaskStatus.SUBMITTED
        assert task.messages == []
        assert task.artifacts == []


# ── Node Initialization ─────────────────────────────────────


class TestNodeInit:
    def test_basic_init(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        assert node._card is card
        assert node._relay is None
        assert node._key_path is None
        assert node._daemon_addr is None
        assert node._home is None
        assert node._daemon_bin is None
        assert not node.is_running
        assert node._task_handlers == []
        assert node._tasks == {}

    def test_init_with_relay(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card, relay="/ip4/1.2.3.4/tcp/4001/p2p/QmRelay")
        assert node._relay == "/ip4/1.2.3.4/tcp/4001/p2p/QmRelay"

    def test_init_with_key_path(self, tmp_path):
        card = AgentCard(name="TestNode")
        key = tmp_path / "identity.key"
        node = Node(card=card, key_path=key)
        assert node._key_path == key

    def test_init_with_daemon_addr(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card, daemon_addr="unix:///tmp/daemon.sock")
        assert node._daemon_addr == "unix:///tmp/daemon.sock"

    def test_init_with_daemon_path(self, tmp_path):
        card = AgentCard(name="TestNode")
        binary = tmp_path / "agentanycastd"
        node = Node(card=card, daemon_path=binary)
        assert node._daemon_bin == binary

    def test_init_daemon_path_takes_precedence_over_daemon_bin(self, tmp_path):
        card = AgentCard(name="TestNode")
        old_bin = tmp_path / "old"
        new_bin = tmp_path / "new"
        node = Node(card=card, daemon_bin=old_bin, daemon_path=new_bin)
        assert node._daemon_bin == new_bin

    def test_init_daemon_bin_fallback(self, tmp_path):
        card = AgentCard(name="TestNode")
        old_bin = tmp_path / "old"
        node = Node(card=card, daemon_bin=old_bin)
        assert node._daemon_bin == old_bin

    def test_init_with_home(self, tmp_path):
        card = AgentCard(name="TestNode")
        node = Node(card=card, home=tmp_path / "my-node")
        assert node._home == tmp_path / "my-node"


# ── Node State Guards ────────────────────────────────────────


class TestNodeStateGuards:
    def test_peer_id_raises_before_start(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        with pytest.raises(RuntimeError, match="Node not started"):
            _ = node.peer_id

    def test_ensure_running_raises_before_start(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        with pytest.raises(RuntimeError, match="Node not started"):
            node._ensure_running()

    def test_is_running_false_initially(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        assert node.is_running is False


# ── on_task Decorator ────────────────────────────────────────


class TestOnTaskDecorator:
    def test_registers_handler(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)

        @node.on_task
        async def my_handler(task):
            pass

        assert len(node._task_handlers) == 1
        assert node._task_handlers[0] is my_handler

    def test_registers_multiple_handlers(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)

        @node.on_task
        async def handler_a(task):
            pass

        @node.on_task
        async def handler_b(task):
            pass

        assert len(node._task_handlers) == 2

    def test_returns_original_function(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)

        async def my_handler(task):
            pass

        result = node.on_task(my_handler)
        assert result is my_handler


# ── Background Task Tracking ────────────────────────────────


class TestBackgroundTaskTracking:
    def test_background_tasks_set_initialized(self):
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        assert isinstance(node._background_tasks, set)
        assert len(node._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_stop_cancels_background_tasks(self):
        """stop() should cancel all background tasks without error."""
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        # Simulate running state without real gRPC
        node._running = True

        # Create a long-running background task
        cancelled = asyncio.Event()

        async def long_running() -> None:
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        bg = asyncio.create_task(long_running())
        node._background_tasks.add(bg)
        bg.add_done_callback(node._background_tasks.discard)

        assert len(node._background_tasks) == 1

        # Let the task start running (reach the await sleep).
        await asyncio.sleep(0)

        # stop() should cancel the background task
        await node.stop()

        assert cancelled.is_set()
        assert len(node._background_tasks) == 0
        assert node._running is False

    @pytest.mark.asyncio
    async def test_done_callback_removes_completed_tasks(self):
        """Completed tasks should be auto-removed from _background_tasks."""
        card = AgentCard(name="TestNode")
        node = Node(card=card)

        completed = asyncio.Event()

        async def quick_task() -> None:
            completed.set()

        bg = asyncio.create_task(quick_task())
        node._background_tasks.add(bg)
        bg.add_done_callback(node._background_tasks.discard)

        await completed.wait()
        # Give the event loop a tick to process the done callback.
        await asyncio.sleep(0.01)

        assert len(node._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_multiple_background_tasks_tracked(self):
        """Multiple tasks should all be tracked and cleaned up."""
        card = AgentCard(name="TestNode")
        node = Node(card=card)
        node._running = True

        events: list[asyncio.Event] = []
        for _ in range(5):
            evt = asyncio.Event()
            events.append(evt)

            async def sleeper(e: asyncio.Event = evt) -> None:
                try:
                    await asyncio.sleep(100)
                except asyncio.CancelledError:
                    e.set()
                    raise

            bg = asyncio.create_task(sleeper())
            node._background_tasks.add(bg)
            bg.add_done_callback(node._background_tasks.discard)

        assert len(node._background_tasks) == 5

        # Let all tasks start running (reach their await sleep).
        await asyncio.sleep(0)

        await node.stop()

        for evt in events:
            assert evt.is_set()
        assert len(node._background_tasks) == 0
