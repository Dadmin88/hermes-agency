"""Peer trust and relay allowlist helpers for Hermes Agency.

The daemon/libp2p layer authenticates connections by Ed25519-derived peer ID.
This module adds the Hermes plugin's local trust store and best-effort relay
allowlist synchronization without modifying the SDK or daemon binary.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from .config import AgencyConfig

logger = logging.getLogger(__name__)

TRUST_LEVELS = {"full", "limited", "blocked"}


class TrustError(RuntimeError):
    """Raised when peer identity verification fails."""


@dataclass(frozen=True)
class TrustDecision:
    """Result of checking a peer against the local trust store."""

    peer_id: str
    allowed: bool
    action: str
    trust_level: str = "limited"
    reason: str = ""
    record: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "allowed": self.allowed,
            "action": self.action,
            "trust_level": self.trust_level,
            "reason": self.reason,
            "record": dict(self.record or {}),
        }


class TrustStore:
    """JSON-backed peer trust store.

    The key is the libp2p peer ID, which is derived from the Ed25519 public key.
    A stable display name is also treated as a TOFU identity hint: if the same
    name later appears with a different peer ID, the connection is rejected and
    reported as a likely key rotation or impersonation event.
    """

    def __init__(self, path: str | Path, *, tofu: bool = True) -> None:
        self.path = Path(path).expanduser()
        self.tofu = bool(tofu)

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "peers": {}}

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except Exception as exc:
            logger.warning("failed to read Hermes Agency trust store %s: %s", self.path, exc)
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        peers = data.setdefault("peers", {})
        if not isinstance(peers, dict):
            data["peers"] = {}
        data.setdefault("version", 1)
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _clean_level(level: str | None) -> str:
        clean = str(level or "limited").strip().lower()
        return clean if clean in TRUST_LEVELS else "limited"

    def list_peers(self) -> dict[str, dict[str, Any]]:
        data = self.load()
        return dict(data.get("peers") or {})

    def set_trust(
        self,
        peer_id: str,
        *,
        trust_level: str = "limited",
        name: str = "",
        owner: str = "",
        source: str = "manual",
    ) -> dict[str, Any]:
        peer_id = str(peer_id or "").strip()
        if not peer_id:
            raise ValueError("peer_id is required")
        now = self._now()
        data = self.load()
        peers = data.setdefault("peers", {})
        existing = dict(peers.get(peer_id) or {})
        record = {
            **existing,
            "peer_id": peer_id,
            "name": str(name or existing.get("name") or "").strip(),
            "owner": str(owner or existing.get("owner") or "").strip(),
            "trust_level": self._clean_level(trust_level),
            "first_seen": existing.get("first_seen") or now,
            "last_seen": now,
            "last_source": source,
        }
        peers[peer_id] = record
        self.save(data)
        return dict(record)

    def verify_peer(
        self,
        peer_id: str,
        *,
        name: str = "",
        owner: str = "",
        trust_level: str = "limited",
        source: str = "runtime",
    ) -> TrustDecision:
        peer_id = str(peer_id or "").strip()
        if not peer_id:
            return TrustDecision("", False, "missing_peer_id", reason="peer_id is required")
        now = self._now()
        clean_name = str(name or "").strip()
        clean_owner = str(owner or "").strip()
        data = self.load()
        peers = data.setdefault("peers", {})
        existing = peers.get(peer_id)
        if existing:
            level = self._clean_level(existing.get("trust_level"))
            if level == "blocked":
                return TrustDecision(
                    peer_id, False, "blocked", level, "peer is blocked", dict(existing)
                )
            existing["last_seen"] = now
            existing["last_source"] = source
            if clean_name and not existing.get("name"):
                existing["name"] = clean_name
            if clean_owner and not existing.get("owner"):
                existing["owner"] = clean_owner
            self.save(data)
            return TrustDecision(peer_id, True, "verified", level, record=dict(existing))

        if clean_name:
            for known_peer_id, record in peers.items():
                if str(record.get("name") or "").strip() == clean_name:
                    level = self._clean_level(record.get("trust_level"))
                    if level != "blocked":
                        return TrustDecision(
                            peer_id,
                            False,
                            "peer_id_mismatch",
                            level,
                            f"name {clean_name!r} was previously trusted as {known_peer_id}",
                            dict(record),
                        )

        if not self.tofu:
            return TrustDecision(
                peer_id, False, "untrusted", reason="TOFU is disabled and peer is unknown"
            )

        record = {
            "peer_id": peer_id,
            "name": clean_name,
            "owner": clean_owner,
            "trust_level": self._clean_level(trust_level),
            "first_seen": now,
            "last_seen": now,
            "last_source": source,
        }
        peers[peer_id] = record
        self.save(data)
        return TrustDecision(
            peer_id, True, "tofu_recorded", record["trust_level"], record=dict(record)
        )


# Backward-compatible helper functions used by NodeManager.


def _trust_path(cfg: AgencyConfig) -> Path:
    if cfg.trust.store_path:
        return Path(cfg.trust.store_path).expanduser()
    return Path.home() / ".hermes" / "agency" / "trust.json"


def store_for_config(cfg: AgencyConfig) -> TrustStore:
    return TrustStore(_trust_path(cfg), tofu=cfg.trust.tofu)


def verify_peer_tofu(
    cfg: AgencyConfig,
    peer_id: str,
    *,
    name: str = "",
    card: dict[str, Any] | None = None,
    source: str = "unknown",
    trust_level: str = "limited",
) -> dict[str, Any] | None:
    """Trust-on-first-use verify one peer ID and return the stored record.

    Raises TrustError for blocked peers or peer-id mismatches.
    """

    peer_id = str(peer_id or "").strip()
    if not peer_id:
        return None
    card_name = ""
    owner = ""
    if isinstance(card, dict):
        card_name = str(card.get("name") or "").strip()
        raw_metadata = card.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        owner = str(card.get("owner") or metadata.get("owner") or "").strip()
    decision = store_for_config(cfg).verify_peer(
        peer_id,
        name=name or card_name,
        owner=owner,
        trust_level=trust_level,
        source=source,
    )
    if not decision.allowed:
        raise TrustError(decision.reason or decision.action)
    return decision.record


def peer_allowed_by_config(cfg: AgencyConfig, peer_id: str) -> bool:
    """Return True if the local configured relay allowlist permits peer_id.

    Empty allowlist means allow-all for backward compatibility.
    """

    allowlist = set(cfg.relay_security.allowlist)
    return not allowlist or str(peer_id or "").strip() in allowlist


def trust_summary(cfg: AgencyConfig) -> dict[str, Any]:
    store = store_for_config(cfg)
    peers = store.list_peers()
    return {
        "store_path": str(store.path),
        "tofu": store.tofu,
        "peer_count": len(peers),
        "peers": peers,
    }


def relay_control_url(cfg: AgencyConfig) -> str | None:
    """Infer the relay REST control URL from config/env-compatible defaults."""

    relay = cfg.relay or ""
    host = ""
    parts = relay.split("/")
    for idx, part in enumerate(parts):
        if part in {"ip4", "ip6", "dns", "dns4", "dns6"} and idx + 1 < len(parts):
            host = parts[idx + 1]
            break
    if not host:
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    # Kyle's VPS relay currently runs the directory/API server on 8083.
    return f"http://{host}:8083"


def sync_relay_allowlist(cfg: AgencyConfig, peer_ids: list[str]) -> dict[str, Any]:
    """Best-effort relay allowlist update via the relay REST API.

    The call is skipped when no token is configured. Empty allowlist semantics are
    preserved on the relay; this helper only appends discovered team peers.
    """

    if not cfg.relay_security.auto_allow_team:
        return {"ok": False, "skipped": True, "reason": "auto_allow_team disabled"}
    token = cfg.relay_security.token
    if not token:
        return {"ok": False, "skipped": True, "reason": "relay token not configured"}
    url = relay_control_url(cfg)
    if not url:
        return {"ok": False, "skipped": True, "reason": "relay API URL unavailable"}
    clean = sorted({str(peer_id).strip() for peer_id in peer_ids if str(peer_id).strip()})
    if not clean:
        return {"ok": True, "skipped": True, "reason": "no peer IDs"}

    payload = json.dumps({"peer_ids": clean}).encode("utf-8")
    req = request.Request(
        f"{url}/api/v1/relay/allowlist",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {"ok": True}
    except error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
