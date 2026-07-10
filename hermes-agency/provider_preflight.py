"""Provider health classification for Hermes Agency preflight checks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{8,}\b"),
)


def _sanitise_provider_error(error_text: str) -> str:
    """Return a compact provider error excerpt with obvious secrets redacted."""

    text = str(error_text or "").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", text
        )
    return text[:500]


@dataclass(frozen=True)
class ProviderHealthResult:
    """A compact, serialisable provider health classification."""

    ok: bool
    category: str
    message: str
    provider: str | None = None
    model: str | None = None
    evidence: str | None = None
    retryable: bool = False
    actions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "category": self.category,
            "message": self.message,
            "provider": self.provider,
            "model": self.model,
            "evidence": self.evidence,
            "retryable": self.retryable,
            "actions": self.actions,
        }


def classify_provider_failure(
    error_text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ProviderHealthResult:
    """Classify provider startup/LLM failures into infrastructure blocker types.

    Hermes worker failures caused by provider quota/auth/outage should be surfaced
    as product infrastructure issues, not as worker protocol violations.
    """

    text = str(error_text or "")
    folded = text.casefold()
    evidence = _sanitise_provider_error(text) or None
    label = "/".join(part for part in (provider, model) if part)
    suffix = f" for {label}" if label else ""

    quota_markers = (
        "429",
        "rate limit",
        "ratelimit",
        "quota",
        "insufficient_quota",
        "usage limit",
        "monthly usage",
        "billing hard limit",
        "credit balance",
    )
    if any(marker in folded for marker in quota_markers):
        return ProviderHealthResult(
            ok=False,
            category="quota_exhausted",
            message=f"Provider quota or usage limit is exhausted{suffix}",
            provider=provider,
            model=model,
            evidence=evidence,
            retryable=False,
            actions=[
                "Restore provider quota/billing or switch the active Agency model set intentionally.",
                "Do not retry Kanban workers until provider health is restored.",
            ],
        )

    auth_markers = (
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "missing api key",
        "authentication",
        "permission denied",
    )
    if any(marker in folded for marker in auth_markers):
        return ProviderHealthResult(
            ok=False,
            category="auth_failed",
            message=f"Provider credentials or permissions failed{suffix}",
            provider=provider,
            model=model,
            evidence=evidence,
            retryable=False,
            actions=[
                "Repair provider credentials/OAuth for the affected Hermes profile.",
                "Run a one-shot smoke test before unblocking Kanban dispatch.",
            ],
        )

    unavailable_markers = (
        "503",
        "502",
        "504",
        "connection refused",
        "connection reset",
        "connectionerror",
        "connect timeout",
        "read timeout",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
    )
    if any(marker in folded for marker in unavailable_markers):
        return ProviderHealthResult(
            ok=False,
            category="provider_unavailable",
            message=f"Provider endpoint is unavailable or timing out{suffix}",
            provider=provider,
            model=model,
            evidence=evidence,
            retryable=True,
            actions=[
                "Wait for provider recovery or switch the active Agency model set intentionally.",
                "Avoid spawning large retry batches while the outage is active.",
            ],
        )

    return ProviderHealthResult(
        ok=False,
        category="unknown_provider_failure",
        message=f"Provider failed with an unclassified error{suffix}",
        provider=provider,
        model=model,
        evidence=evidence,
        retryable=False,
        actions=[
            "Inspect the captured provider error and classify it before retrying at scale.",
        ],
    )


def provider_health_ok(
    *, provider: str | None = None, model: str | None = None
) -> ProviderHealthResult:
    """Return an explicit healthy provider result for checks without live failures."""

    return ProviderHealthResult(
        ok=True,
        category="ok",
        message="No provider failure detected",
        provider=provider,
        model=model,
        retryable=False,
        actions=[],
    )


def preflight_provider_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    catalog: Any | None = None,
) -> ProviderHealthResult:
    """Config-level provider/model health preflight for dispatch routing.

    This deliberately avoids making a live LLM call in the dispatcher. It catches
    deterministic bad routes (unknown provider/model in the Agency catalog) and
    provides a small seam for future smoke probes without spawning a doomed
    worker first.
    """

    provider = str(provider or "").strip()
    model = str(model or "").strip()
    if not provider or not model:
        return ProviderHealthResult(
            ok=False,
            category="unknown_provider_failure",
            message="Provider/model preflight requires non-empty provider and model",
            provider=provider or None,
            model=model or None,
            retryable=False,
            actions=["Fix the Agency task-routing tier to name a provider and model."],
        )

    if catalog is None:
        try:
            from .model_sets import load_catalog

            catalog = load_catalog()
        except Exception as exc:
            return ProviderHealthResult(
                ok=False,
                category="unknown_provider_failure",
                message=f"Could not load Agency model catalog for preflight: {type(exc).__name__}: {exc}",
                provider=provider,
                model=model,
                retryable=False,
                actions=["Repair the Agency model catalog before enabling task routing."],
            )

    providers = getattr(catalog, "providers", {}) if catalog is not None else {}
    provider_meta = providers.get(provider) if isinstance(providers, dict) else None
    if not isinstance(provider_meta, dict):
        return ProviderHealthResult(
            ok=False,
            category="unknown_provider_failure",
            message=f"Unknown provider in Agency model catalog: {provider}",
            provider=provider,
            model=model,
            retryable=False,
            actions=["Choose a provider present in hermes-agency/model_catalog.yaml."],
        )
    models = provider_meta.get("models") if isinstance(provider_meta.get("models"), dict) else {}
    if model not in models:
        return ProviderHealthResult(
            ok=False,
            category="unknown_provider_failure",
            message=f"Unknown model for provider {provider}: {model}",
            provider=provider,
            model=model,
            retryable=False,
            actions=["Choose a model present in hermes-agency/model_catalog.yaml."],
        )
    return provider_health_ok(provider=provider, model=model)
