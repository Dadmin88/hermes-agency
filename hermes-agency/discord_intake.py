"""Discord channel intake for Hermes Agency tasks.

This is a polling MVP: messages that begin with a configured prefix are turned
into orchestrator-owned Kanban tasks. A systemd timer, cron job, or manual CLI
call can run the poller.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .discord_bridge import (
    _DISCORD_API,
    _USER_AGENT,
    _get_bot_token,
    _get_bridge_channel_id,
    _post_discord,
)
from .kanban_bridge import create_task as kanban_create_task
from .node_manager import manager

STATE_FILENAME = "discord_intake_state.json"
DEFAULT_PREFIX = "!agency"
_ALLOWED_USER_IDS_ENV = "HERMES_AGENCY_DISCORD_ALLOWED_USER_IDS"
_ALLOWED_ROLE_IDS_ENV = "HERMES_AGENCY_DISCORD_ALLOWED_ROLE_IDS"


def _split_config_ids(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value).replace(";", ",").split(",")
    return {str(item).strip() for item in items if str(item).strip()}


def _agency_config_value(key: str) -> Any:
    try:
        config = __import__("hermes_cli.config", fromlist=["cfg_get", "load_config"])
        return config.cfg_get(config.load_config(), "agency", key, default="")
    except Exception:
        return ""


def discord_allowed_user_ids() -> set[str]:
    return _split_config_ids(os.getenv(_ALLOWED_USER_IDS_ENV, "")) or _split_config_ids(
        _agency_config_value("discord_allowed_user_ids")
    )


def discord_allowed_role_ids() -> set[str]:
    return _split_config_ids(os.getenv(_ALLOWED_ROLE_IDS_ENV, "")) or _split_config_ids(
        _agency_config_value("discord_allowed_role_ids")
    )


def _root_hermes_home() -> Path:
    hermes_home = os.getenv("HERMES_HOME", "").strip()
    active_home = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    if active_home.parent.name == "profiles":
        return active_home.parent.parent
    return active_home


def state_path() -> Path:
    override = os.getenv("HERMES_AGENCY_DISCORD_INTAKE_STATE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _root_hermes_home() / "agency" / STATE_FILENAME


def discord_task_prefix() -> str:
    env_value = os.getenv("HERMES_AGENCY_DISCORD_TASK_PREFIX", "").strip()
    if env_value:
        return env_value
    try:
        from hermes_cli.config import cfg_get, load_config

        value = str(
            cfg_get(load_config(), "agency", "discord_task_prefix", default="") or ""
        ).strip()
        return value or DEFAULT_PREFIX
    except Exception:
        return DEFAULT_PREFIX


def _load_state() -> dict[str, Any]:
    path = state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _discord_request(path: str, *, params: dict[str, Any] | None = None) -> Any:
    token = _get_bot_token()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    req = urllib.request.Request(
        f"{_DISCORD_API}{path}{query}",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_recent_messages(*, limit: int = 25) -> list[dict[str, Any]]:
    channel_id = _get_bridge_channel_id()
    if not channel_id:
        raise RuntimeError("Discord bridge channel is not configured")
    payload = _discord_request(
        f"/channels/{channel_id}/messages", params={"limit": max(1, min(limit, 100))}
    )
    if not isinstance(payload, list):
        raise RuntimeError("Discord API returned an unexpected message payload")
    return [item for item in payload if isinstance(item, dict)]


def _message_author(message: dict[str, Any]) -> str:
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    username = str(author.get("username") or "").strip()
    discriminator = str(author.get("discriminator") or "").strip()
    if username and discriminator and discriminator != "0":
        return f"{username}#{discriminator}"
    return username or str(author.get("id") or "unknown")


def _message_role_ids(message: dict[str, Any]) -> set[str]:
    member = message.get("member") if isinstance(message.get("member"), dict) else {}
    return _split_config_ids(member.get("roles") if isinstance(member, dict) else None)


def _sender_authorized(
    message: dict[str, Any], *, allowed_user_ids: set[str], allowed_role_ids: set[str]
) -> bool:
    if not allowed_user_ids and not allowed_role_ids:
        return False
    author = message.get("author") if isinstance(message.get("author"), dict) else {}
    author_id = str(author.get("id") or "").strip()
    if author_id and author_id in allowed_user_ids:
        return True
    return bool(_message_role_ids(message) & allowed_role_ids)


def _parse_task_message(message: dict[str, Any], *, prefix: str) -> str | None:
    content = str(message.get("content") or "").strip()
    if not content.lower().startswith(prefix.lower()):
        return None
    task_text = content[len(prefix) :].strip()
    if task_text.lower().startswith("task "):
        task_text = task_text[5:].strip()
    if task_text.lower() in {"", "help", "status"}:
        return None
    return task_text or None


def _create_orchestrator_task(task_text: str, message: dict[str, Any]) -> dict[str, Any]:
    author = _message_author(message)
    message_id = str(message.get("id") or "")
    channel_id = str(message.get("channel_id") or _get_bridge_channel_id() or "")
    metadata = {
        "agency_kind": "discord_intake",
        "discord_message_id": message_id,
        "discord_channel_id": channel_id,
        "discord_author": author,
        "discord_created_at": message.get("timestamp"),
    }
    kanban = kanban_create_task(
        title=task_text[:80].rstrip() or "Discord agency task",
        description=f"Discord task from {author}:\n\n{task_text}",
        assigned_to="agency-orchestrator",
        skills=["orchestration", "task-routing"],
        dependencies=[],
        metadata=metadata,
    )
    local = manager.create_orchestrator_task(
        task_text,
        kind="discord_intake",
        target_agent="agency-orchestrator",
        status="active",
        metadata={
            **metadata,
            "kanban_task_id": (kanban.get("task_id") if isinstance(kanban, dict) else None),
        },
    )
    return {
        "message_id": message_id,
        "author": author,
        "task_text": task_text,
        "kanban": kanban,
        "local_task": local,
    }


def poll_discord_tasks(
    *, limit: int = 25, dry_run: bool = False, ack: bool = True
) -> dict[str, Any]:
    prefix = discord_task_prefix()
    allowed_user_ids = discord_allowed_user_ids()
    allowed_role_ids = discord_allowed_role_ids()
    state = _load_state()
    processed_ids = set(str(item) for item in state.get("processed_message_ids") or [])
    try:
        messages = list(reversed(fetch_recent_messages(limit=limit)))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "dry_run": dry_run,
            "prefix": prefix,
            "authorization_required": True,
            "allowed_user_count": len(allowed_user_ids),
            "allowed_role_count": len(allowed_role_ids),
            "queued_count": 0,
            "skipped_count": 0,
            "queued": [],
            "state_path": str(state_path()),
        }

    queued: list[dict[str, Any]] = []
    skipped = 0
    for message in messages:
        message_id = str(message.get("id") or "")
        if not message_id or message_id in processed_ids:
            skipped += 1
            continue
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        if bool(author.get("bot")):
            processed_ids.add(message_id)
            skipped += 1
            continue
        if not _sender_authorized(
            message,
            allowed_user_ids=allowed_user_ids,
            allowed_role_ids=allowed_role_ids,
        ):
            skipped += 1
            continue
        task_text = _parse_task_message(message, prefix=prefix)
        if not task_text:
            skipped += 1
            continue
        if dry_run:
            queued.append(
                {
                    "message_id": message_id,
                    "author": _message_author(message),
                    "task_text": task_text,
                    "dry_run": True,
                }
            )
        else:
            created = _create_orchestrator_task(task_text, message)
            queued.append(created)
            if ack:
                task_id = None
                kanban = created.get("kanban") if isinstance(created.get("kanban"), dict) else {}
                if kanban.get("available") and kanban.get("ok"):
                    task_id = kanban.get("task_id")
                task_id = task_id or (created.get("local_task") or {}).get("task_id")
                _post_discord(f"Queued agency task `{task_id}` for agency-orchestrator.")
        processed_ids.add(message_id)
    if not dry_run:
        state["processed_message_ids"] = sorted(processed_ids)[-500:]
        state["updated_at"] = time.time()
        state["prefix"] = prefix
        _save_state(state)
    return {
        "ok": True,
        "dry_run": dry_run,
        "prefix": prefix,
        "authorization_required": True,
        "allowed_user_count": len(allowed_user_ids),
        "allowed_role_count": len(allowed_role_ids),
        "queued_count": len(queued),
        "skipped_count": skipped,
        "queued": queued,
        "state_path": str(state_path()),
    }


def render_poll_result(payload: dict[str, Any]) -> str:
    lines = [
        "Discord intake poll",
        f"  ok: {payload.get('ok')}",
        f"  prefix: {payload.get('prefix')}",
        f"  authorized users: {payload.get('allowed_user_count', 0)}; roles: {payload.get('allowed_role_count', 0)}",
        f"  queued: {payload.get('queued_count', 0)}",
        f"  skipped: {payload.get('skipped_count', 0)}",
        f"  dry_run: {payload.get('dry_run')}",
        f"  state: {payload.get('state_path')}",
    ]
    if payload.get("error"):
        lines.append(f"  error: {payload.get('error')}")
    for item in payload.get("queued") or []:
        task_id = None
        kanban = item.get("kanban") if isinstance(item.get("kanban"), dict) else {}
        if kanban.get("available") and kanban.get("ok"):
            task_id = kanban.get("task_id")
        local = item.get("local_task") if isinstance(item.get("local_task"), dict) else {}
        task_id = task_id or local.get("task_id") or item.get("message_id")
        lines.append(f"    - {task_id}: {item.get('task_text')}")
    return "\n".join(lines)
