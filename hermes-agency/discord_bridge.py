"""Optional Discord bridge for Hermes Agency A2A message visibility.

Normal Discord delivery should happen through the Hermes gateway's regular
response flow: the model receives the A2A tool result and posts its final reply
to the current channel/thread. This module is intentionally disabled unless an
explicit bridge channel is configured, because a hardcoded channel ID breaks
thread routing and can create duplicate/404 posts.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"
_USER_AGENT = "Hermes Agency (https://github.com/DeployFaith/hermes-agentanycast, v0.1.0)"

_token_cache: str | None = None
_token_checked = False
_channel_cache: str | None = None
_channel_checked = False

_TOKEN_PREFIX = "DISCORD_BOT_TOKEN="


def _get_bot_token() -> str | None:
    """Read the Discord bot token from .env."""
    global _token_cache, _token_checked
    if _token_checked:
        return _token_cache
    _token_checked = True

    hermes_home = os.environ.get("HERMES_HOME", "")
    profile_name = os.environ.get("HERMES_PROFILE", "")

    candidates = []
    if profile_name:
        candidates.append(os.path.expanduser(f"~/.hermes/profiles/{profile_name}/.env"))
    if hermes_home:
        candidates.append(os.path.join(hermes_home, ".env"))
    candidates.append(os.path.expanduser("~/.hermes/.env"))

    for path in candidates:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(_TOKEN_PREFIX):
                        _token_cache = line[len(_TOKEN_PREFIX) :].strip()
                        return _token_cache
        except OSError:
            continue
    return None


def _get_bridge_channel_id() -> str | None:
    """Return the explicitly configured Discord bridge channel/thread ID.

    No default is intentional. If this is unset, normal gateway delivery handles
    Discord output and this bridge stays quiet.
    """

    global _channel_cache, _channel_checked
    if _channel_checked:
        return _channel_cache
    _channel_checked = True

    channel_id = os.getenv("AGENTANYCAST_DISCORD_CHANNEL_ID", "").strip()
    if not channel_id:
        try:
            from hermes_cli.config import cfg_get, load_config

            channel_id = str(
                cfg_get(load_config(), "agency", "discord_channel_id", default="") or ""
            ).strip()
        except Exception:
            channel_id = ""
    _channel_cache = channel_id or None
    return _channel_cache


def _post_discord(content: str) -> bool:
    """Post a message to an explicitly configured Discord channel/thread."""

    channel_id = _get_bridge_channel_id()
    if not channel_id:
        logger.debug("Hermes Agency Discord bridge channel not configured; skipping post")
        return False

    token = _get_bot_token()
    if not token:
        logger.debug("No DISCORD_BOT_TOKEN found, skipping Discord post")
        return False

    url = f"{_DISCORD_API}/channels/{channel_id}/messages"
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        logger.warning("Discord bridge post failed for channel %s: %s", channel_id, exc)
        return False


# ── Public API ──────────────────────────────────────────────────────


def notify_message_sent(sender_name: str, message: str) -> None:
    """Post when this agent sends a message. Just the message itself."""
    _post_discord(message)


def notify_message_received(receiver_name: str, response: str) -> None:
    """Post when this agent responds. Just the response itself."""
    _post_discord(response)


def notify_status(profile_name: str, status: str) -> None:
    """Post a short status update."""
    _post_discord(status)
