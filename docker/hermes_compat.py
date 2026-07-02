#!/usr/bin/env python3
"""Small standalone Hermes compatibility layer for container runs.

Hermes Agency normally runs as a Hermes plugin.  The Docker image also supports a
self-contained mode for evaluation and local deployments where the full Hermes
runtime is not installed.  This module provides the narrow subset of
``hermes_constants`` and ``hermes_cli`` APIs used by the agency dashboard, staff
installer, and Kanban bridge.

When a real Hermes runtime is installed, these shims are not used.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import sys
import time
import types
import uuid
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_CURRENT_BOARD: ContextVar[str | None] = ContextVar("hermes_agency_container_board", default=None)
DEFAULT_BOARD = "default"
_BOARD_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "/data/hermes")).expanduser()


def _config_path() -> Path:
    return _hermes_home() / "config.yaml"


def _cfg_get(config: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = config
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _ensure_home() -> Path:
    home = _hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "profiles").mkdir(parents=True, exist_ok=True)
    return home


def _atomic_yaml_write(path: str | Path, data: dict[str, Any], *, sort_keys: bool = False) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to write YAML")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=sort_keys), encoding="utf-8")
    tmp.replace(target)


def _board_root() -> Path:
    return _hermes_home() / "kanban" / "boards"


def _normalise_board(board: str | None = None) -> str:
    slug = (board or _CURRENT_BOARD.get() or DEFAULT_BOARD).strip().lower() or DEFAULT_BOARD
    if not _BOARD_SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid Kanban board slug: {slug!r}")
    return slug


def _board_path(*parts: str) -> Path:
    root = _board_root().resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Kanban board path escapes board root")
    return path


def _db_path(board: str | None = None) -> Path:
    slug = _normalise_board(board)
    if slug == DEFAULT_BOARD:
        return _hermes_home() / "kanban.db"
    return _board_path(slug, "kanban.db")


def _board_dir(board: str | None = None) -> Path:
    return _board_path(_normalise_board(board))


def _now() -> int:
    return int(time.time())


def _task_id() -> str:
    return "t_" + uuid.uuid4().hex[:8]


def _jsonable(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


@dataclass
class Task:
    id: str
    title: str
    body: str
    assignee: str | None
    status: str
    priority: int
    tenant: str | None
    workspace_kind: str | None
    workspace_path: str | None
    branch_name: str | None
    created_by: str | None
    created_at: float | None
    started_at: float | None
    completed_at: float | None
    result: str | None
    skills: list[str]
    idempotency_key: str | None
    session_id: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row | None) -> Task | None:
        if row is None:
            return None
        try:
            skills = json.loads(row["skills"] or "[]")
        except Exception:
            skills = []
        return cls(
            id=row["id"],
            title=row["title"] or "",
            body=row["body"] or "",
            assignee=row["assignee"],
            status=row["status"] or "todo",
            priority=int(row["priority"] or 0),
            tenant=row["tenant"],
            workspace_kind=row["workspace_kind"],
            workspace_path=row["workspace_path"],
            branch_name=row["branch_name"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=row["result"],
            skills=skills if isinstance(skills, list) else [],
            idempotency_key=row["idempotency_key"],
            session_id=row["session_id"],
        )


@dataclass
class Comment:
    id: int
    task_id: str
    author: str
    body: str
    created_at: float


@dataclass
class Event:
    id: int
    task_id: str
    kind: str
    payload: Any
    created_at: float
    run_id: int | None = None


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          body TEXT DEFAULT '',
          assignee TEXT,
          status TEXT DEFAULT 'todo',
          priority INTEGER DEFAULT 0,
          tenant TEXT,
          workspace_kind TEXT,
          workspace_path TEXT,
          branch_name TEXT,
          created_by TEXT,
          created_at REAL,
          started_at REAL,
          completed_at REAL,
          result TEXT,
          skills TEXT,
          idempotency_key TEXT,
          session_id TEXT
        );
        CREATE TABLE IF NOT EXISTS task_comments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          author TEXT NOT NULL,
          body TEXT NOT NULL,
          created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          payload TEXT,
          created_at REAL NOT NULL,
          run_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS task_links (
          parent_id TEXT NOT NULL,
          child_id TEXT NOT NULL,
          PRIMARY KEY(parent_id, child_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
        CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        """
    )
    conn.commit()


def init_db() -> Path:
    _ensure_home()
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        _init_schema(conn)
    return path


@contextlib.contextmanager
def connect_closing() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _init_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def scoped_current_board(slug: str) -> Iterator[None]:
    token: Token[str | None] = _CURRENT_BOARD.set(slug)
    try:
        yield
    finally:
        _CURRENT_BOARD.reset(token)


def get_current_board() -> str:
    return _normalise_board()


def board_exists(board: str | None = None) -> bool:
    slug = _normalise_board(board)
    return (
        slug == DEFAULT_BOARD
        or (_board_dir(slug) / "board.json").exists()
        or _db_path(slug).exists()
    )


def create_board(
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    default_workdir: str | None = None,
) -> dict[str, Any]:
    del icon, color, default_workdir
    slug = _normalise_board(slug)
    directory = _board_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "slug": slug,
        "name": name or slug.replace("-", " ").title(),
        "description": description or "",
        "created_at": _now(),
        "db_path": str(_db_path(slug)),
    }
    (directory / "board.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    with scoped_current_board(slug):
        init_db()
    return meta


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    body: str = "",
    assignee: str | None = None,
    created_by: str | None = None,
    parents: tuple[str, ...] = (),
    skills: list[str] | None = None,
    idempotency_key: str | None = None,
    session_id: str | None = None,
    tenant: str | None = None,
    priority: int = 0,
    initial_status: str = "running",
    **_: Any,
) -> str:
    if idempotency_key:
        row = conn.execute(
            (
                "SELECT id FROM tasks WHERE idempotency_key = ? AND status != 'archived' "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            (idempotency_key,),
        ).fetchone()
        if row:
            return str(row["id"])
    tid = _task_id()
    now = _now()
    conn.execute(
        """
        INSERT INTO tasks
        (id, title, body, assignee, status, priority, tenant, workspace_kind, workspace_path,
         branch_name, created_by, created_at, started_at, completed_at, result, skills,
         idempotency_key, session_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tid,
            title,
            body,
            assignee,
            initial_status,
            priority,
            tenant,
            None,
            None,
            None,
            created_by,
            now,
            now if initial_status == "running" else None,
            None,
            None,
            json.dumps(skills or []),
            idempotency_key,
            session_id,
        ),
    )
    for parent in parents:
        conn.execute(
            "INSERT OR IGNORE INTO task_links(parent_id, child_id) VALUES (?, ?)",
            (parent, tid),
        )
    _append_event(conn, tid, "created", {"status": initial_status})
    return tid


def get_task(conn: sqlite3.Connection, task_id: str) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return Task.from_row(row)


def list_tasks(
    conn: sqlite3.Connection,
    *,
    assignee: str | None = None,
    status: str | None = None,
    tenant: str | None = None,
    session_id: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
    order_by: str | None = None,
    **_: Any,
) -> list[Task]:
    del order_by
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if assignee is not None:
        query += " AND assignee = ?"
        params.append(assignee)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if tenant is not None:
        query += " AND tenant = ?"
        params.append(tenant)
    if session_id is not None:
        query += " AND session_id = ?"
        params.append(session_id)
    if not include_archived:
        query += " AND status != 'archived'"
    query += " ORDER BY COALESCE(completed_at, started_at, created_at, 0) DESC, id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(limit))
    rows = conn.execute(query, tuple(params)).fetchall()
    return [task for row in rows if (task := Task.from_row(row)) is not None]


def parent_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT parent_id FROM task_links WHERE child_id = ?",
        (task_id,),
    )
    return [r["parent_id"] for r in rows]


def child_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT child_id FROM task_links WHERE parent_id = ?",
        (task_id,),
    )
    return [r["child_id"] for r in rows]


def add_comment(conn: sqlite3.Connection, task_id: str, author: str, body: str) -> int:
    cur = conn.execute(
        "INSERT INTO task_comments(task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (task_id, author, body, _now()),
    )
    return int(cur.lastrowid)


def list_comments(conn: sqlite3.Connection, task_id: str) -> list[Comment]:
    rows = conn.execute(
        "SELECT * FROM task_comments WHERE task_id = ? ORDER BY id ASC",
        (task_id,),
    ).fetchall()
    return [
        Comment(
            id=r["id"],
            task_id=r["task_id"],
            author=r["author"],
            body=r["body"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def _append_event(
    conn: sqlite3.Connection,
    task_id: str,
    kind: str,
    payload: Any = None,
    run_id: int | None = None,
) -> int:
    cur = conn.execute(
        (
            "INSERT INTO task_events(task_id, kind, payload, created_at, run_id) "
            "VALUES (?, ?, ?, ?, ?)"
        ),
        (task_id, kind, _jsonable(payload), _now(), run_id),
    )
    return int(cur.lastrowid)


def list_events(conn: sqlite3.Connection, task_id: str) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC",
        (task_id,),
    ).fetchall()
    events: list[Event] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if row["payload"] else None
        except Exception:
            payload = row["payload"]
        events.append(
            Event(
                id=row["id"],
                task_id=row["task_id"],
                kind=row["kind"],
                payload=payload,
                created_at=row["created_at"],
                run_id=row["run_id"],
            )
        )
    return events


def recompute_ready(conn: sqlite3.Connection) -> None:
    del conn


def _install_module(name: str, module: types.ModuleType) -> None:
    if name not in sys.modules:
        sys.modules[name] = module


def install() -> None:
    """Install compatibility modules only when the real Hermes runtime is absent."""
    try:
        import hermes_constants  # noqa: F401
    except Exception:
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = _hermes_home
        constants.get_default_hermes_root = _hermes_home
        _install_module("hermes_constants", constants)

    try:
        from hermes_cli import config as _real_config  # noqa: F401
    except Exception:
        hermes_cli = sys.modules.get("hermes_cli") or types.ModuleType("hermes_cli")
        config = types.ModuleType("hermes_cli.config")
        config.cfg_get = _cfg_get
        config.load_config = _load_config
        config.get_config_path = _config_path
        config.ensure_hermes_home = _ensure_home
        hermes_cli.config = config  # type: ignore[attr-defined]
        _install_module("hermes_cli", hermes_cli)
        _install_module("hermes_cli.config", config)

    try:
        from hermes_cli import kanban_db as _real_kanban  # noqa: F401
    except Exception:
        hermes_cli = sys.modules.get("hermes_cli") or types.ModuleType("hermes_cli")
        kanban = types.ModuleType("hermes_cli.kanban_db")
        for name, value in {
            "DEFAULT_BOARD": DEFAULT_BOARD,
            "Task": Task,
            "Comment": Comment,
            "Event": Event,
            "init_db": init_db,
            "connect_closing": connect_closing,
            "scoped_current_board": scoped_current_board,
            "get_current_board": get_current_board,
            "board_exists": board_exists,
            "create_board": create_board,
            "create_task": create_task,
            "get_task": get_task,
            "list_tasks": list_tasks,
            "parent_ids": parent_ids,
            "child_ids": child_ids,
            "add_comment": add_comment,
            "list_comments": list_comments,
            "list_events": list_events,
            "recompute_ready": recompute_ready,
            "_append_event": _append_event,
        }.items():
            setattr(kanban, name, value)
        hermes_cli.kanban_db = kanban  # type: ignore[attr-defined]
        _install_module("hermes_cli", hermes_cli)
        _install_module("hermes_cli.kanban_db", kanban)

    try:
        import utils  # noqa: F401
    except Exception:
        utils = types.ModuleType("utils")
        utils.atomic_yaml_write = _atomic_yaml_write
        _install_module("utils", utils)
