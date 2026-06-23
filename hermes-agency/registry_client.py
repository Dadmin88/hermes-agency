"""Registry refresh client and health tracking for Hermes Agency nodes."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from .card_builder import build_card
from .config import AgencyConfig, current_profile_name, get_config

REGISTRY_REREGISTER_INTERVAL_SECONDS = 20
REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS = 1
REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS = 60
REGISTRY_REREGISTER_FAILURE_LOG_EVERY = 5
REGISTRY_HEALTHY_WINDOW_SECONDS = 60

logger = logging.getLogger(__name__)


def _registry_addresses() -> list[str]:
    """Return configured Hermes Agency registry gRPC addresses.

    The daemon reads ``AGENTANYCAST_REGISTRY_ADDRS`` for initial registration.
    The relay registry TTL is currently 30s, so the plugin also uses the same
    env var for periodic refreshes while the node is alive.
    """

    raw = os.getenv("AGENTANYCAST_REGISTRY_ADDRS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


class RegistryClientMixin:
    """Relay skill-registry refresh and health logic."""

    def _refresh_registration_health(self) -> None:
        last_success = self.state.last_registration_time
        self.state.registration_healthy = bool(
            self.state.started
            and last_success is not None
            and time.time() - last_success < REGISTRY_HEALTHY_WINDOW_SECONDS
        )

    def _registration_health_dict(self) -> dict[str, Any]:
        self._refresh_registration_health()
        return {
            "last_registration_time": self.state.last_registration_time,
            "consecutive_failures": self.state.consecutive_failures,
            "next_retry_at": self.state.next_retry_at,
            "registration_healthy": self.state.registration_healthy,
            "registry_reregister_loop_exited": self.state.registry_reregister_loop_exited,
            "loop_running": bool(
                self._registry_reregister_task is not None
                and not self._registry_reregister_task.done()
            ),
            "healthy_window_seconds": REGISTRY_HEALTHY_WINDOW_SECONDS,
            "normal_interval_seconds": REGISTRY_REREGISTER_INTERVAL_SECONDS,
        }

    def _record_registry_registration_success(self) -> None:
        now = time.time()
        previous_failures = self.state.consecutive_failures
        self.state.last_registration_time = now
        self.state.consecutive_failures = 0
        self.state.next_retry_at = now + REGISTRY_REREGISTER_INTERVAL_SECONDS
        self.state.registry_reregister_loop_exited = False
        self._refresh_registration_health()
        if previous_failures:
            logger.warning(
                "Hermes Agency relay skill re-registration recovered after %s consecutive failures",
                previous_failures,
            )

    def _record_registry_registration_failure(self, details: str, retry_in_seconds: float) -> None:
        now = time.time()
        self.state.consecutive_failures += 1
        self.state.next_retry_at = now + retry_in_seconds
        self._refresh_registration_health()
        self.state.last_status = f"Registry refresh failed: {details}"
        logger.warning(
            "Hermes Agency relay skill re-registration failed "
            "(consecutive_failures=%s, retry_in=%.1fs): %s",
            self.state.consecutive_failures,
            retry_in_seconds,
            details,
        )
        if self.state.consecutive_failures % REGISTRY_REREGISTER_FAILURE_LOG_EVERY == 0:
            logger.warning(
                "Hermes Agency relay skill re-registration still failing after %s consecutive failures; "
                "last_success=%s next_retry_at=%s",
                self.state.consecutive_failures,
                self.state.last_registration_time,
                self.state.next_retry_at,
            )

    def _handle_registry_registration_result(
        self,
        result: dict[str, Any],
        *,
        retry_in_seconds: float,
    ) -> bool | None:
        if result.get("skipped"):
            self._refresh_registration_health()
            return None
        if result.get("ok"):
            self._record_registry_registration_success()
            return True
        errors = result.get("errors") or [result.get("error") or "unknown registry refresh failure"]
        self._record_registry_registration_failure(
            "; ".join(str(item) for item in errors), retry_in_seconds
        )
        return False

    @staticmethod
    def _registry_skill_id(skill: Any) -> str:
        if isinstance(skill, dict):
            return str(skill.get("id") or skill.get("skill_id") or skill.get("name") or "").strip()
        return str(
            getattr(skill, "id", "") or getattr(skill, "skill_id", "") or getattr(skill, "name", "")
        ).strip()

    @staticmethod
    def _registry_skill_description(skill: Any) -> str:
        if isinstance(skill, dict):
            return str(skill.get("description") or "").strip()
        return str(getattr(skill, "description", "") or "").strip()

    @staticmethod
    def _registry_token_metadata(
        config: AgencyConfig, addr: str
    ) -> tuple[tuple[str, str], ...] | None:
        """Return registry auth metadata when safe or explicitly allowed."""

        token = config.relay_security.token
        if not token:
            return None

        # Registry refresh currently uses grpc.aio.insecure_channel for every
        # configured address. Never leak bearer-style tokens across that channel
        # unless the user explicitly opts in for a trusted local network.
        if not config.registry_allow_insecure_token_transport:
            logger.warning(
                "Configured registry token: not sending registry token over insecure gRPC "
                "to %s. Set agency.registry.allow_insecure_token_transport=true only for "
                "trusted local networks if this registry requires token metadata.",
                addr,
            )
            return None

        logger.warning(
            "Configured registry token: sending registry token over insecure gRPC to %s "
            "because agency.registry.allow_insecure_token_transport=true.",
            addr,
        )
        return (
            ("authorization", f"Bearer {token}"),
            ("x-agency-relay-token", token),
        )

    async def _register_skills_with_registries(self, card: Any) -> dict[str, Any]:
        """Refresh this node's relay skill-registry TTL.

        The Go daemon currently registers skills once shortly after startup. The
        relay expires registry entries after 30 seconds, so long-lived Hermes
        gateways need an application-level refresh until the daemon owns this
        heartbeat itself.
        """

        if not self.state.peer_id:
            return {"ok": False, "skipped": True, "reason": "peer_id is not set"}
        addresses = _registry_addresses()
        if not addresses:
            return {
                "ok": False,
                "skipped": True,
                "reason": "AGENTANYCAST_REGISTRY_ADDRS is not set",
            }

        import importlib

        import grpc

        registry_pb2 = importlib.import_module(
            "agentanycast._generated.agentanycast.v1.registry_service_pb2"
        )
        registry_grpc = importlib.import_module(
            "agentanycast._generated.agentanycast.v1.registry_service_pb2_grpc"
        )
        skills = []
        for item in getattr(card, "skills", []) or []:
            skill_id = self._registry_skill_id(item)
            if not skill_id:
                continue
            skills.append(
                registry_pb2.SkillInfo(
                    skill_id=skill_id,
                    description=self._registry_skill_description(item),
                )
            )
        if not skills:
            return {"ok": False, "skipped": True, "reason": "card has no registry skill IDs"}

        request = registry_pb2.RegisterSkillsRequest(
            peer_id=self.state.peer_id,
            agent_name=str(
                getattr(card, "name", "") or self.state.card_name or current_profile_name()
            ),
            agent_description=str(getattr(card, "description", "") or ""),
            skills=skills,
        )

        errors: list[str] = []
        for addr in addresses:
            channel = grpc.aio.insecure_channel(addr)
            try:
                stub = registry_grpc.RegistryServiceStub(channel)
                call_metadata = self._registry_token_metadata(self.state.config, addr)
                if call_metadata:
                    await stub.RegisterSkills(request, timeout=5, metadata=call_metadata)
                else:
                    await stub.RegisterSkills(request, timeout=5)
            except Exception as exc:  # keep node alive; report in status
                errors.append(f"{addr}: {type(exc).__name__}: {exc}")
            finally:
                await channel.close()
        if errors:
            self.state.last_status = "Registry refresh failed: " + "; ".join(errors)
            return {
                "ok": False,
                "skipped": False,
                "errors": errors,
                "addresses": addresses,
                "skill_count": len(skills),
            }
        self.state.last_status = f"Registry refreshed ({len(skills)} skills)."
        return {
            "ok": True,
            "skipped": False,
            "errors": [],
            "addresses": addresses,
            "skill_count": len(skills),
        }

    async def _registry_reregister_loop(self) -> None:
        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
        backoff = float(REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS)
        cancelled = False
        try:
            while True:
                self.state.next_retry_at = time.time() + next_delay
                await asyncio.sleep(next_delay)
                try:
                    cfg = get_config()
                    if not cfg.team.auto_register:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        self._refresh_registration_health()
                        continue
                    if self._node is None or not self.state.started:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        self._refresh_registration_health()
                        continue
                    result = await self._register_skills_with_registries(build_card())
                    outcome = self._handle_registry_registration_result(
                        result,
                        retry_in_seconds=backoff,
                    )
                    if outcome is False:
                        next_delay = backoff
                        backoff = min(backoff * 2, REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS)
                    else:
                        next_delay = float(REGISTRY_REREGISTER_INTERVAL_SECONDS)
                        backoff = float(REGISTRY_REREGISTER_INITIAL_BACKOFF_SECONDS)
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                except Exception as exc:
                    self._record_registry_registration_failure(
                        f"{type(exc).__name__}: {exc}",
                        backoff,
                    )
                    next_delay = backoff
                    backoff = min(backoff * 2, REGISTRY_REREGISTER_MAX_BACKOFF_SECONDS)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException as exc:
            self.state.registry_reregister_loop_exited = True
            self._refresh_registration_health()
            logger.critical(
                "Hermes Agency relay skill re-registration loop exited unexpectedly: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise
        finally:
            if not cancelled and self.state.started:
                self.state.registry_reregister_loop_exited = True
                self._refresh_registration_health()
                logger.critical(
                    "Hermes Agency relay skill re-registration loop exited unexpectedly"
                )

    def _registry_reregister_done(self, task: asyncio.Task[None]) -> None:
        """Record and restart any unexpected relay re-registration task exit."""

        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        self.state.registry_reregister_loop_exited = True
        self._refresh_registration_health()
        if exc is not None:
            self.state.error = f"registry re-registration loop failed: {type(exc).__name__}: {exc}"
            logger.critical(
                "Hermes Agency relay skill re-registration task exited; restarting: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        else:
            self.state.error = "registry re-registration loop exited unexpectedly"
            logger.critical("Hermes Agency relay skill re-registration task exited; restarting")
        if self.state.started and self._loop is not None and self._loop.is_running():
            self._registry_reregister_task = self._loop.create_task(
                self._registry_reregister_loop()
            )
            self._registry_reregister_task.add_done_callback(self._registry_reregister_done)
