"""Authenticated, crash-recoverable audit checkpoint anchor."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import uuid
from pathlib import Path
from typing import Any

from .validation import canonical_json


class HMACAuditAnchor:
    """Durable HMAC anchor with a two-phase pending/committed protocol.

    Production should place ``key_path`` and ``anchor_path`` in a promoter-owned,
    permission-separated directory. The MAC still prevents a database/checkpoint
    rewriter that does not possess the anchor key from manufacturing a valid head.
    """

    def __init__(self, key_path: Path, anchor_path: Path):
        self.key_path = key_path
        self.anchor_path = anchor_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        try:
            fd = os.open(self.key_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            fd = os.open(
                self.key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o400,
            )
            key = secrets.token_bytes(32)
            try:
                os.write(fd, key)
                os.fsync(fd)
            finally:
                os.close(fd)
            return key
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
                raise PermissionError("audit anchor key must be one private regular file")
            key = os.read(fd, 33)
        finally:
            os.close(fd)
        if len(key) != 32:
            raise RuntimeError("audit anchor key has invalid length")
        return key

    def _sign(self, payload: dict[str, Any]) -> str:
        return hmac.new(self._key, canonical_json(payload), hashlib.sha256).hexdigest()

    def _write(self, payload: dict[str, Any]) -> None:
        envelope = {"payload": payload, "mac": self._sign(payload)}
        temp = self.anchor_path.with_name(f".{self.anchor_path.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, json.dumps(envelope, sort_keys=True).encode() + b"\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, self.anchor_path)
        parent_fd = os.open(self.anchor_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def read(self) -> dict[str, Any] | None:
        if not self.anchor_path.exists():
            return None
        fd = os.open(self.anchor_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError("audit anchor is not a regular file")
            raw = os.read(fd, 16385)
        finally:
            os.close(fd)
        if len(raw) > 16384:
            raise RuntimeError("audit anchor is oversized")
        envelope = json.loads(raw)
        payload = envelope.get("payload")
        mac = envelope.get("mac")
        if not isinstance(payload, dict) or not isinstance(mac, str):
            raise RuntimeError("audit anchor envelope is invalid")
        if not hmac.compare_digest(mac, self._sign(payload)):
            raise RuntimeError("audit anchor authentication failed")
        return payload

    def bootstrap(self, head: dict[str, Any]) -> None:
        current = self.read()
        if current is None:
            self._write({"version": 1, "committed": head, "pending": None})

    def prepare(self, old_head: dict[str, Any], new_head: dict[str, Any]) -> None:
        current = self.read()
        if (
            current is None
            or current.get("committed") != old_head
            or current.get("pending") is not None
        ):
            raise RuntimeError("audit anchor is not at the transaction baseline")
        self._write({"version": 1, "committed": old_head, "pending": new_head})

    def finalize(self, new_head: dict[str, Any]) -> None:
        current = self.read()
        if current is None or current.get("pending") != new_head:
            raise RuntimeError("audit anchor has no matching pending commit")
        self._write({"version": 1, "committed": new_head, "pending": None})

    def reconcile(self, database_head: dict[str, Any]) -> bool:
        current = self.read()
        if current is None:
            return False
        if current.get("committed") == database_head and current.get("pending") is None:
            return True
        if current.get("pending") == database_head:
            self.finalize(database_head)
            return True
        if current.get("committed") == database_head and current.get("pending") is not None:
            self._write({"version": 1, "committed": database_head, "pending": None})
            return True
        return False
