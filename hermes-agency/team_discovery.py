"""Team discovery, context refresh, and relay allowlist syncing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .card_builder import build_card
from .config import AgencyConfig, get_config
from .registration import update_registration
from .team_context import build_team_context, get_team_state, refresh_capability_map
from .trust import (
    TrustError,
    peer_allowed_by_config,
    store_for_config,
    sync_relay_allowlist,
    verify_peer_tofu,
)

logger = logging.getLogger(__name__)


class TeamDiscoveryMixin:
    """Peer/team discovery and team-context refresh logic."""

    def _refresh_team_state_fields(self) -> None:
        team_state = get_team_state()
        self.state.team_peer_count = len(team_state.peers)
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
        if str(trust_record.get("trust_level") or "").strip().lower() == "blocked":
            return False
        if peer_allowed_by_config(cfg, clean):
            return True
        return clean in set(self.effective_relay_allowlist(cfg))

    def _verify_team_peers(self, cfg: AgencyConfig) -> None:
        for peer in get_team_state().peers.values():
            try:
                verify_peer_tofu(
                    cfg,
                    peer.peer_id,
                    name=peer.card_name or peer.name,
                    card={"name": peer.card_name or peer.name},
                    source="team_discovery",
                    trust_level="full",
                )
            except TrustError as exc:
                logger.warning("Hermes Agency TOFU rejected discovered peer: %s", exc)

    async def _sync_effective_relay_allowlist(self, cfg: AgencyConfig) -> dict[str, Any]:
        return await asyncio.to_thread(
            sync_relay_allowlist, cfg, self.effective_relay_allowlist(cfg)
        )

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
