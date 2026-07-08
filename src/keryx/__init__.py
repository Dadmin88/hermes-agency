"""AgentAnycast-compatible adapter backed by the Keryx Python SDK.

This package intentionally presents the same public imports used by
``agentanycast`` while resolving Keryx SDK implementation modules from the
adjacent Hermes_Keryx checkout.  The local modules in this package provide the
AgentAnycast-compatible facades; missing submodules (``client``, ``config``,
``models``, ``did``, etc.) are loaded from the real Keryx SDK package path.
"""

from __future__ import annotations

import os
from pathlib import Path

# Default to the monorepo layout used by Hermes Agency/Keryx development, while
# allowing deployments to point at a vendored or installed Keryx SDK checkout.
_SDK_PACKAGE_PATH = Path(
    os.environ.get(
        "HERMES_KERYX_SDK_PACKAGE",
        str(Path.home() / "repos" / "Hermes_Keryx" / "sdk" / "python" / "keryx"),
    )
).expanduser()


def _ensure_sdk_package_path() -> None:
    """Expose Keryx SDK submodules through this package's search path."""

    sdk_path = str(_SDK_PACKAGE_PATH)
    if _SDK_PACKAGE_PATH.exists() and sdk_path not in __path__:
        __path__.append(sdk_path)


_ensure_sdk_package_path()


def peer_id_to_did_key(peer_id: str) -> str:
    """Convert a libp2p PeerID to did:key using the Keryx SDK helper."""

    from keryx.did import peer_id_to_did_key as _peer_id_to_did_key  # type: ignore[import-not-found]

    return _peer_id_to_did_key(peer_id)


from keryx.card import AgentCard, Skill  # noqa: E402
from keryx.node import Node  # noqa: E402
from keryx.task import (  # noqa: E402
    Artifact,
    IncomingTask,
    Message,
    Part,
    Task,
    TaskCanceledError,
    TaskFailedError,
    TaskHandle,
    TaskRejectedError,
    TaskStatus,
    TaskTimeoutError,
)

__all__ = [
    "Node",
    "AgentCard",
    "Skill",
    "peer_id_to_did_key",
    "Part",
    "Message",
    "Artifact",
    "Task",
    "TaskHandle",
    "IncomingTask",
    "TaskStatus",
    "TaskTimeoutError",
    "TaskFailedError",
    "TaskCanceledError",
    "TaskRejectedError",
]
