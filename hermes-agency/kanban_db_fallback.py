"""Minimal Kanban DB fallback for Agency-only runtimes.

Hermes Agency normally delegates Kanban persistence to ``hermes_cli.kanban_db``.
Some repo/runtime smoke paths load the Agency plugin without the full Hermes CLI
package installed, but still need outbound delegation tracking to create and
update the canonical ``~/.hermes/kanban.db`` rows.  This module intentionally
implements only the subset of the Hermes Kanban API used by ``kanban_bridge``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CURRENT_BOARD: ContextVar[str | None] = ContextVar("hermes_agency_fallback_board", default=None)
DEFAULT_BOARD = "default"
_BOARD_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def _board_root() -> Path:
    return _hermes_home() / "kanban" / "boards"


def _default_db_path() -> Path:
    env_path = os.environ.get("HERMES_KANBAN_DB")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return (_hermes_home() / "kanban.db").resolve()


def _normalise_board(board: str | None = None) -> str:
    slug = str(board or _CURRENT_BOARD.get() or DEFAULT_BOARD).strip().lower() or DEFAULT_BOARD
    if not _BOARD_SLUG_RE.fullmatch(slug):
        raise ValueError(f"invalid Kanban board slug: {slug!r}")
    return slug


def _board_path(*parts: str) -> Path:
    root = _board_root().resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Kanban board path escapes board root")
    return path


def kanban_db_path(board: str | None = None) -> Path:
    slug = _normalise_board(board)
    if slug == DEFAULT_BOARD:
        return _default_db_path()
    return _board_path(slug, "kanban.db")


def _board_dir(board: str | None = None) -> Path:
    return _board_path(_normalise_board(board))


def board_metadata_path(board: str) -> Path:
    return _board_dir(board) / "board.json"


def read_board_metadata(board: str) -> dict[str, Any]:
    path = board_metadata_path(board)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _now() -> int:
    return int(time.time())


def _task_id() -> str:
    return "t_" + uuid.uuid4().hex[:8]


def _jsonable(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


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
    claim_lock: str | None = None
    claim_expires: float | None = None
    worker_pid: int | None = None
    last_heartbeat_at: float | None = None
    current_run_id: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row | None) -> Task | None:
        if row is None:
            return None
        try:
            skills = json.loads(_row_value(row, "skills", "[]") or "[]")
        except Exception:
            skills = []
        return cls(
            id=str(_row_value(row, "id", "")),
            title=str(_row_value(row, "title", "") or ""),
            body=str(_row_value(row, "body", "") or ""),
            assignee=_row_value(row, "assignee"),
            status=str(_row_value(row, "status", "todo") or "todo"),
            priority=int(_row_value(row, "priority", 0) or 0),
            tenant=_row_value(row, "tenant"),
            workspace_kind=_row_value(row, "workspace_kind"),
            workspace_path=_row_value(row, "workspace_path"),
            branch_name=_row_value(row, "branch_name"),
            created_by=_row_value(row, "created_by"),
            created_at=_row_value(row, "created_at"),
            started_at=_row_value(row, "started_at"),
            completed_at=_row_value(row, "completed_at"),
            result=_row_value(row, "result"),
            skills=skills if isinstance(skills, list) else [],
            idempotency_key=_row_value(row, "idempotency_key"),
            session_id=_row_value(row, "session_id"),
            claim_lock=_row_value(row, "claim_lock"),
            claim_expires=_row_value(row, "claim_expires"),
            worker_pid=_row_value(row, "worker_pid"),
            last_heartbeat_at=_row_value(row, "last_heartbeat_at"),
            current_run_id=_row_value(row, "current_run_id"),
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
        CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key);
        """
    )
    conn.commit()


def init_db() -> Path:
    path = kanban_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        _init_schema(conn)
    return path


@contextlib.contextmanager
def connect_closing() -> Iterator[sqlite3.Connection]:
    path = kanban_db_path()
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


@contextlib.contextmanager
def write_txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_current_board() -> str:
    return _normalise_board()


def board_exists(board: str | None = None) -> bool:
    slug = _normalise_board(board)
    return (
        slug == DEFAULT_BOARD or board_metadata_path(slug).exists() or kanban_db_path(slug).exists()
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
        "db_path": str(kanban_db_path(slug)),
    }
    board_metadata_path(slug).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
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
            "SELECT id FROM tasks WHERE idempotency_key = ? AND status != 'archived' "
            "ORDER BY created_at DESC LIMIT 1",
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
            "scratch",
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
        if parent:
            conn.execute(
                "INSERT OR IGNORE INTO task_links(parent_id, child_id) VALUES (?, ?)",
                (parent, tid),
            )
    _append_event(conn, tid, "created", {"assignee": assignee, "status": initial_status})
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
    clauses = []
    params: list[Any] = []
    if assignee:
        clauses.append("assignee = ?")
        params.append(assignee)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if tenant:
        clauses.append("tenant = ?")
        params.append(tenant)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if not include_archived:
        clauses.append("status != 'archived'")
    sql = "SELECT * FROM tasks"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by in {"created_at", "started_at", "completed_at", "priority"}:
        sql += f" ORDER BY {order_by} DESC"
    else:
        sql += " ORDER BY COALESCE(started_at, created_at, 0) DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [
        task for row in conn.execute(sql, tuple(params)).fetchall() if (task := Task.from_row(row))
    ]


def parent_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
    ).fetchall()
    return [str(row["parent_id"]) for row in rows]


def child_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)
    ).fetchall()
    return [str(row["child_id"]) for row in rows]


def link_tasks(conn: sqlite3.Connection, parent_id: str, child_id: str) -> bool:
    conn.execute(
        "INSERT OR IGNORE INTO task_links(parent_id, child_id) VALUES (?, ?)",
        (parent_id, child_id),
    )
    _append_event(conn, child_id, "linked", {"parent_id": parent_id})
    return True


def add_comment(conn: sqlite3.Connection, task_id: str, author: str, body: str) -> int:
    cur = conn.execute(
        "INSERT INTO task_comments(task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (task_id, author, body, _now()),
    )
    return int(cur.lastrowid or 0)


def list_comments(conn: sqlite3.Connection, task_id: str) -> list[Comment]:
    rows = conn.execute(
        "SELECT id, task_id, author, body, created_at FROM task_comments WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    return [
        Comment(
            id=int(row["id"]),
            task_id=str(row["task_id"]),
            author=str(row["author"]),
            body=str(row["body"]),
            created_at=float(row["created_at"]),
        )
        for row in rows
    ]


def _append_event(
    conn: sqlite3.Connection,
    task_id: str,
    kind: str,
    payload: Any = None,
    *,
    run_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO task_events(task_id, kind, payload, created_at, run_id) VALUES (?, ?, ?, ?, ?)",
        (task_id, kind, _jsonable(payload), _now(), run_id),
    )


def list_events(conn: sqlite3.Connection, task_id: str) -> list[Event]:
    rows = conn.execute(
        "SELECT id, task_id, kind, payload, created_at, run_id FROM task_events WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    events: list[Event] = []
    for row in rows:
        payload: Any = row["payload"]
        if payload:
            try:
                payload = json.loads(payload)
            except Exception:
                pass
        events.append(
            Event(
                id=int(row["id"]),
                task_id=str(row["task_id"]),
                kind=str(row["kind"]),
                payload=payload,
                created_at=float(row["created_at"]),
                run_id=row["run_id"],
            )
        )
    return events


def recompute_ready(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id FROM tasks WHERE status = 'todo'").fetchall()
    for row in rows:
        unfinished = conn.execute(
            "SELECT 1 FROM task_links l JOIN tasks p ON p.id = l.parent_id "
            "WHERE l.child_id = ? AND p.status NOT IN ('done', 'archived') LIMIT 1",
            (row["id"],),
        ).fetchone()
        if not unfinished:
            conn.execute("UPDATE tasks SET status = 'ready' WHERE id = ?", (row["id"],))


def assign_task(conn: sqlite3.Connection, task_id: str, assignee: str | None) -> bool:
    cur = conn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", (assignee, task_id))
    if cur.rowcount:
        _append_event(conn, task_id, "assigned", {"assignee": assignee})
    return bool(cur.rowcount)


def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    result: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
    **_: Any,
) -> bool:
    del summary
    cur = conn.execute(
        "UPDATE tasks SET status = 'done', result = ?, completed_at = COALESCE(completed_at, ?) WHERE id = ?",
        (result, _now(), task_id),
    )
    if cur.rowcount:
        _append_event(conn, task_id, "completed", metadata or {"result": result})
    return bool(cur.rowcount)


def block_task(
    conn: sqlite3.Connection, task_id: str, *, reason: str | None = None, **_: Any
) -> bool:
    cur = conn.execute(
        "UPDATE tasks SET status = 'blocked', result = ?, completed_at = COALESCE(completed_at, ?) WHERE id = ?",
        (reason, _now(), task_id),
    )
    if cur.rowcount:
        _append_event(conn, task_id, "blocked", {"reason": reason})
    return bool(cur.rowcount)
