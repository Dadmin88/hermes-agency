"""Drop-in AgentAnycast compatibility surface backed by Keryx."""

from __future__ import annotations

import warnings

warnings.warn(
    "agentanycast is deprecated, use keryx",
    DeprecationWarning,
    stacklevel=2,
)

from keryx import AgentCard, IncomingTask, Task  # noqa: E402
from keryx import KeryxNode as Node  # noqa: E402
from keryx.did import peer_id_to_did_key  # noqa: E402
from keryx.registration import deregister_agent, register_agent  # noqa: E402

__all__ = [
    "Node",
    "AgentCard",
    "Task",
    "IncomingTask",
    "peer_id_to_did_key",
    "register_agent",
    "deregister_agent",
]