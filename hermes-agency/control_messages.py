"""Control-message handling for incoming Hermes Agency tasks."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def handle_control_message(manager: Any, task: Any, message_text: str, cfg: Any) -> bool:
    """Handle an incoming control message if the payload parses as one.

    Returns True when the incoming task was a control message and was fully
    handled (accepted or rejected). Returns False when the text is not a control
    payload and normal task queuing should continue.
    """

    nm = manager._nm()
    control_payload = nm.parse_control_message(message_text)
    if not control_payload:
        return False

    security = nm.verify_incoming_sender(
        task, cfg, purpose="control", control_payload=control_payload
    )
    if not security.allowed:
        try:
            await task.fail(security.reason)
        except Exception:
            pass
        logger.warning(
            "Hermes Agency rejected incoming control message from %s: %s",
            security.sender_peer_id or "unknown peer",
            security.reason,
        )
        return True

    control_result = nm.handle_registration_message(control_payload) or nm.handle_bid_message(
        control_payload
    )
    if control_result is None:
        control_result = {"ok": False, "ignored": True, "type": control_payload.get("type")}
    manager._refresh_autonomous_state()
    try:
        if control_payload.get("type") == "registration":
            agent = (
                (control_payload.get("agent") or {}).get("name")
                if isinstance(control_payload.get("agent"), dict)
                else control_payload.get("peer_id")
            )
            nm.announce_registration(
                agent or control_payload.get("peer_id"),
                str(control_payload.get("event") or "received"),
                peer_id=str(control_payload.get("peer_id") or ""),
            )
        await task.complete(
            artifacts=[
                {
                    "artifact_id": f"agency-control-{getattr(task, 'task_id', 'unknown')}",
                    "name": "agency-control-ack",
                    "parts": [{"text": json.dumps(control_result, sort_keys=True, default=str)}],
                }
            ]
        )
    except Exception:
        pass
    return True
