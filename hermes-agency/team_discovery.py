"""Team discovery, context refresh, and relay allowlist syncing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .card_builder import build_card, card_to_dict
from .config import AgencyConfig, add_peer_to_relay_allowlist, get_config
from .registration import serialize_control_message, update_registration
from .team_context import (
    build_team_context,
    filter_team_peers,
    get_team_state,
    refresh_capability_map,
    visible_team_peer_count,
)
from .trust import (
    TrustError,
    handshake_due,
    peer_allowed_by_config,
    record_peer_handshake_attempt,
    store_for_config,
    sync_relay_allowlist,
    trust_peer_for_handshake,
    verify_peer_tofu,
)

logger = logging.getLogger(__name__)


class TeamDiscoveryMixin:
    """Peer/team discovery and team-context refresh logic."""

    def _refresh_team_state_fields(self) -> None:
        team_state = get_team_state()
        self.state.team_peer_count = visible_team_peer_count(self.state.config)
        self.state.team_last_refresh = team_state.last_refresh
        self.state.team_last_error = team_state.last_error
        self.state.team_context = build_team_context(self.state.config)

    def effective_relay_allowlist(self, config: AgencyConfig | None = None) -> list[str]:
        """Return explicit allowlist plus verified team peers when enabled.

        Empty allowlist is deny-by-default unless ``agency.relay.allow_all`` is
        explicitly set. Auto-added team peers must already have a non-blocked
        trust-store record; discovery alone is not sufficient.
        """

        cfg = config or get_config()
        trusted_records = store_for_config(cfg).list_peers()
        seen: set[str] = set()
        allowlist: list[str] = []
        for peer_id in cfg.relay_security.allowlist:
            clean = str(peer_id or "").strip()
            if clean and clean not in seen:
                seen.add(clean)
                allowlist.append(clean)
        for peer_id, trust_record in trusted_records.items():
            clean = str(peer_id or "").strip()
            if not clean or clean in seen:
                continue
            trust_level = str(trust_record.get("trust_level") or "").strip().lower()
            handshake_status = str(trust_record.get("handshake_status") or "").strip().lower()
            if trust_level == "full" or (
                trust_level == "limited" and handshake_status in {"sent", "accepted"}
            ):
                seen.add(clean)
                allowlist.append(clean)
        if cfg.relay_security.auto_allow_team:
            for peer_id in sorted(get_team_state().peers):
                clean = str(peer_id or "").strip()
                if not clean or clean in seen:
                    continue
                trust_record = trusted_records.get(clean) or {}
                trust_level = str(trust_record.get("trust_level") or "").strip().lower()
                if trust_level in {"limited", "full"}:
                    seen.add(clean)
                    allowlist.append(clean)
        return allowlist

    def _peer_allowed_by_effective_allowlist(self, cfg: AgencyConfig, peer_id: str) -> bool:
        clean = str(peer_id or "").strip()
        if not clean:
            return False
        trust_record = store_for_config(cfg).list_peers().get(clean) or {}
        trust_level = str(trust_record.get("trust_level") or "").strip().lower()
        if trust_level == "blocked":
            logger.debug(
                "Hermes Agency send allowlist check denied blocked peer_id=%s trust_record=%s",
                clean,
                trust_record,
            )
            return False
        # Full-trust peers are allowed to receive direct outbound tasks even when
        # they have not been persisted into the explicit config allowlist yet.
        if trust_level == "full":
            logger.debug(
                "Hermes Agency send allowlist check allowed full-trust peer_id=%s trust_record=%s",
                clean,
                trust_record,
            )
            return True
        config_allowed = peer_allowed_by_config(cfg, clean)
        if config_allowed:
            logger.debug(
                "Hermes Agency send allowlist check allowed configured peer_id=%s config_allowed=%s trust_record=%s",
                clean,
                config_allowed,
                trust_record,
            )
            return True
        effective_allowed = clean in set(self.effective_relay_allowlist(cfg))
        logger.debug(
            "Hermes Agency send allowlist check peer_id=%s config_allowed=%s effective_allowed=%s trust_record=%s",
            clean,
            config_allowed,
            effective_allowed,
            trust_record,
        )
        return effective_allowed

    def _verify_team_peers(self, cfg: AgencyConfig) -> None:
        for peer in get_team_state().peers.values():
            try:
                verify_peer_tofu(
                    cfg,
                    peer.peer_id,
                    name=peer.card_name or peer.name,
                    card={"name": peer.card_name or peer.name},
                    source="team_discovery",
                    trust_level="limited",
                )
            except TrustError as exc:
                logger.warning("Hermes Agency TOFU rejected discovered peer: %s", exc)

    async def _sync_effective_relay_allowlist(self, cfg: AgencyConfig) -> dict[str, Any]:
        return await asyncio.to_thread(
            sync_relay_allowlist, cfg, self.effective_relay_allowlist(cfg)
        )

    @staticmethod
    def _handshake_peer_id(peer: Any) -> str:
        if isinstance(peer, dict):
            return str(peer.get("peer_id") or peer.get("id") or "").strip()
        return str(getattr(peer, "peer_id", "") or getattr(peer, "id", "") or "").strip()

    @staticmethod
    def _handshake_peer_name(peer: Any) -> str:
        if isinstance(peer, dict):
            return str(
                peer.get("card_name") or peer.get("name") or peer.get("agent_name") or ""
            ).strip()
        return str(
            getattr(peer, "card_name", "")
            or getattr(peer, "name", "")
            or getattr(peer, "agent_name", "")
            or ""
        ).strip()

    @staticmethod
    def _handshake_peer_card(peer: Any) -> dict[str, Any]:
        if isinstance(peer, dict):
            return {
                "name": str(peer.get("card_name") or peer.get("name") or "").strip(),
                "description": str(
                    peer.get("card_description") or peer.get("description") or ""
                ).strip(),
                "skills": peer.get("card_skills") or peer.get("skills") or [],
            }
        return {
            "name": str(getattr(peer, "card_name", "") or getattr(peer, "name", "") or "").strip(),
            "description": str(
                getattr(peer, "card_description", "") or getattr(peer, "description", "") or ""
            ).strip(),
            "skills": getattr(peer, "card_skills", None) or getattr(peer, "skills", None) or [],
        }

    def _roster_handshake_candidates(self) -> list[dict[str, Any]]:
        """Return online roster peers whose peer IDs are available.

        Only returns peers currently visible in the team state (connected
        to the relay).  Offline peers cannot receive handshake messages,
        so attempting them wastes relay circuit retries and can trigger
        a network storm that overloads the gateway.
        """

        try:
            from .pool.roster import build_roster

            # Startup team refresh already has a live peer map from the active
            # node.  Loading the roster through its default Keryx live-discovery
            # path can block startup/CLI discovery when the registry or gateway
            # is slow.  Use the static/persisted roster only, then intersect it
            # with currently visible peer IDs below before attempting handshakes.
            roster = build_roster(live_peers=[], include_plugin_setup=False)
        except Exception:
            return []

        # Build set of currently-connected peer IDs from team state.
        visible_ids: set[str] = set()
        try:
            for peer in (get_team_state().peers or {}).values():
                pid = str(getattr(peer, "peer_id", "") or "").strip()
                if pid:
                    visible_ids.add(pid)
        except Exception:
            pass

        candidates: list[dict[str, Any]] = []
        for agent in roster.get("profiles") or []:
            if not isinstance(agent, dict):
                continue
            peer_id = str(agent.get("peer_id") or "").strip()
            if not peer_id:
                continue
            # Skip offline peers — handshake delivery will fail and retry.
            if peer_id not in visible_ids:
                continue
            candidates.append(
                {
                    "peer_id": peer_id,
                    "name": str(agent.get("name") or "").strip(),
                    "description": str(agent.get("description") or "").strip(),
                    "skills": agent.get("capabilities") or agent.get("skills") or [],
                }
            )
        return candidates

    def _handshake_payload(self) -> dict[str, Any] | None:
        local_peer_id = str(self.state.peer_id or "").strip()
        if not local_peer_id:
            return None
        try:
            local_card = card_to_dict(build_card())
        except Exception:
            local_card = {"name": self.state.card_name or "", "description": "", "skills": []}
        return {
            "protocol": "agency.autonomous.v1",
            "type": "handshake",
            "event": "hello",
            "peer_id": local_peer_id,
            "agent": {
                "name": str(local_card.get("name") or self.state.card_name or "").strip(),
                "description": str(local_card.get("description") or "").strip(),
                "skills": local_card.get("skills") or [],
                "tenant": self.state.config.team.tenant,
            },
            "timestamp": time.time(),
        }

    async def _attempt_peer_handshake(self, cfg: AgencyConfig, peer: Any) -> dict[str, Any] | None:
        """Ensure one peer is trusted, allowlisted, and sent our peer ID."""

        if self._node is None or not self.state.started:
            return None
        peer_id = self._handshake_peer_id(peer)
        if not peer_id or peer_id == self.state.peer_id:
            return None
        if not handshake_due(cfg, peer_id):
            return None
        name = self._handshake_peer_name(peer)
        card = self._handshake_peer_card(peer)
        try:
            trust_peer_for_handshake(
                cfg,
                peer_id,
                name=name,
                card=card,
                direction="outgoing",
                source="auto_handshake_discovery",
            )
            try:
                allowlist_result = await asyncio.to_thread(add_peer_to_relay_allowlist, peer_id)
            except Exception as exc:
                allowlist_result = {
                    "ok": False,
                    "changed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "peer_id": peer_id,
                }
            payload = self._handshake_payload()
            if payload is None:
                record_peer_handshake_attempt(
                    cfg,
                    peer_id,
                    status="queued",
                    name=name,
                    direction="outgoing",
                    error="local peer_id unavailable",
                    source="auto_handshake_discovery",
                )
                return {"ok": False, "peer_id": peer_id, "queued": True}
            message_text = serialize_control_message(payload)
            await self._node.send_task(
                message={"role": "user", "parts": [{"text": message_text}]},
                peer_id=peer_id,
                metadata={
                    "agency_control": "handshake",
                    "type": "handshake",
                    "sender_peer_id": str(self.state.peer_id or ""),
                },
            )
            record_peer_handshake_attempt(
                cfg,
                peer_id,
                status="sent",
                name=name,
                direction="outgoing",
                source="auto_handshake_discovery",
            )
            return {"ok": True, "peer_id": peer_id, "allowlist": allowlist_result}
        except TrustError as exc:
            logger.warning("Hermes Agency auto-handshake rejected peer %s: %s", peer_id, exc)
            return {"ok": False, "peer_id": peer_id, "error": str(exc), "rejected": True}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                record_peer_handshake_attempt(
                    cfg,
                    peer_id,
                    status="failed",
                    name=name,
                    direction="outgoing",
                    error=error,
                    source="auto_handshake_discovery",
                )
            except Exception:
                pass
            logger.debug("Hermes Agency auto-handshake failed for %s: %s", peer_id, error)
            return {"ok": False, "peer_id": peer_id, "error": error}

    async def _perform_auto_handshakes(self, cfg: AgencyConfig) -> list[dict[str, Any]]:
        """Handshake with discovered online peers that have peer IDs."""

        visible_peers = filter_team_peers(get_team_state().peers, cfg)
        peers: list[Any] = [*visible_peers.values(), *self._roster_handshake_candidates()]
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for i, peer in enumerate(peers):
            peer_id = self._handshake_peer_id(peer)
            if not peer_id or peer_id in seen:
                continue
            seen.add(peer_id)
            result = await self._attempt_peer_handshake(cfg, peer)
            if result is not None:
                results.append(result)
            # Rate-limit: pause every 5 attempts to avoid relay storms.
            if i > 0 and i % 5 == 0:
                await asyncio.sleep(1)
        if any(item.get("ok") for item in results):
            refreshed_cfg = get_config()
            self.state.config = refreshed_cfg
            relay_result = await self._sync_effective_relay_allowlist(refreshed_cfg)
            if not relay_result.get("ok") and not relay_result.get("skipped"):
                logger.warning("Hermes Agency relay allowlist sync failed: %s", relay_result)
        return results

    async def _refresh_team_context_impl(self, *, force: bool = False) -> None:
        cfg = get_config()
        self.state.config = cfg
        if not cfg.team.auto_discover:
            self._refresh_team_state_fields()
            return
        now = time.time()
        team_state = get_team_state()
        refresh_seconds = max(60, cfg.team.context_refresh_minutes * 60)
        if (
            not force
            and team_state.last_refresh
            and now - team_state.last_refresh < refresh_seconds
        ):
            self._refresh_team_state_fields()
            return
        if self._node is None or not self.state.started:
            self._refresh_team_state_fields()
            return
        try:
            await refresh_capability_map(
                self._node,
                local_peer_id=self.state.peer_id,
                local_card=build_card(),
            )
            if cfg.team.auto_register:
                await update_registration(
                    self._node,
                    build_card(),
                    current_load=self._current_load(),
                )
            await self._perform_auto_handshakes(cfg)
            cfg = get_config()
            self.state.config = cfg
            if cfg.relay_security.auto_allow_team:
                self._verify_team_peers(cfg)
                relay_result = await self._sync_effective_relay_allowlist(cfg)
                if not relay_result.get("ok") and not relay_result.get("skipped"):
                    logger.warning("Hermes Agency relay allowlist sync failed: %s", relay_result)
        finally:
            self._refresh_team_state_fields()
            self._refresh_autonomous_state()

    async def _team_refresh_loop(self) -> None:
        while True:
            cfg = get_config()
            await asyncio.sleep(max(60, cfg.team.context_refresh_minutes * 60))
            await self._refresh_team_context_impl(force=True)
