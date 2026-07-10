"""Task-aware conservative model routing for Hermes Agency Kanban workers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .model_sets import DEFAULT_MODEL_SET, ModelSet, load_model_set
from .provider_preflight import ProviderHealthResult, preflight_provider_model, provider_health_ok

SAFE_PROVIDER = "openai-codex"
SAFE_MODEL = "gpt-5.5"
SAFE_TIER = "safe_default"
ROUTE_METADATA_KEY = "agency_model_route"


@dataclass(frozen=True)
class TaskRoutingContext:
    task_id: str | None = None
    title: str = ""
    body: str = ""
    assignee: str | None = None
    board: str | None = None
    priority: int | None = None
    parents: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    prior_attempts: int = 0
    prior_failures: int = 0
    status: str | None = None

    @classmethod
    def from_task(
        cls, task: Any, *, board: str | None = None, metadata: dict[str, Any] | None = None
    ) -> TaskRoutingContext:
        def _list(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, str):
                return [value] if value else []
            try:
                return [str(item) for item in value if item]
            except TypeError:
                return []

        meta = dict(metadata or {})
        labels = _list(meta.get("labels") or meta.get("risk_tags") or meta.get("tags"))
        return cls(
            task_id=str(getattr(task, "id", "") or "") or None,
            title=str(getattr(task, "title", "") or ""),
            body=str(getattr(task, "body", "") or ""),
            assignee=str(getattr(task, "assignee", "") or "") or None,
            board=board,
            priority=getattr(task, "priority", None),
            parents=_list(meta.get("parents")),
            children=_list(meta.get("children")),
            skills=_list(getattr(task, "skills", None) or meta.get("skills")),
            labels=labels,
            metadata=meta,
            prior_attempts=_int(meta.get("prior_attempts") or meta.get("run_count"), 0),
            prior_failures=_int(
                meta.get("prior_failures")
                or meta.get("failure_count")
                or getattr(task, "consecutive_failures", 0),
                0,
            ),
            status=str(getattr(task, "status", "") or "") or None,
        )


@dataclass(frozen=True)
class ModelRouteDecision:
    provider: str
    model: str
    tier: str
    family: str | None
    source: str
    confidence: float
    reasons: list[str]
    matched_rules: list[str]
    risk_tags: list[str]
    preflight: dict[str, Any]
    fallback_used: bool = False
    block_reason: str | None = None

    @property
    def model_override(self) -> str | None:
        if self.block_reason:
            return None
        return f"{self.model} --provider {self.provider}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def metadata(self) -> dict[str, Any]:
        data = self.as_dict()
        data.pop("family", None)
        if len(data.get("reasons") or []) > 5:
            data["reasons"] = data["reasons"][:5]
        return {ROUTE_METADATA_KEY: data}


PreflightFn = Callable[[str, str], ProviderHealthResult]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def default_task_routing_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "mode": "conservative",
        "default": {"provider": SAFE_PROVIDER, "model": SAFE_MODEL, "tier": SAFE_TIER},
        "health": {
            "preflight": "config",
            "cache_ttl_seconds": 300,
            "block_if_safe_default_unhealthy": True,
        },
        "classifier": {
            "downgrade_min_confidence": 0.85,
            "uncertain_goes_to_default": True,
            "long_context_parent_threshold": 3,
            "long_context_body_chars": 12000,
            "repeated_failure_threshold": 1,
        },
        "tiers": {
            SAFE_TIER: {
                "provider": SAFE_PROVIDER,
                "model": SAFE_MODEL,
                "reason": "Safe fallback for all Agency workers.",
            },
            "light_docs": {
                "provider": SAFE_PROVIDER,
                "model": SAFE_MODEL,
                "reason": "Placeholder low-risk docs tier.",
            },
            "light_readonly": {
                "provider": SAFE_PROVIDER,
                "model": SAFE_MODEL,
                "reason": "Placeholder low-risk read-only tier.",
            },
        },
        "escalation": {
            "force_tier": SAFE_TIER,
            "assignees": [
                "agency-orchestrator",
                "agency-software-architect",
                "agency-systems-architect",
                "agency-security-reviewer",
                "agency-code-reviewer",
                "agency-release-manager",
            ],
            "keyword_rules": {
                "security_keyword": {
                    "any": ["security", "secret", "credential", "auth", "privacy"],
                    "tags": ["security"],
                },
                "architecture_keyword": {
                    "any": ["architecture", "design", "boundary", "api design", "system design"],
                    "tags": ["architecture"],
                },
                "release_keyword": {
                    "any": ["release", "deploy", "production", "rollback", "migration"],
                    "tags": ["release"],
                },
                "review_keyword": {
                    "any": ["review", "approval", "signoff", "merge readiness"],
                    "tags": ["code_review"],
                },
                "destructive_keyword": {
                    "any": ["delete", "destructive", "rewrite", "bulk", "irreversible"],
                    "tags": ["destructive_change"],
                },
                "orchestration_keyword": {
                    "any": ["orchestrate", "decompose", "fan out", "route work"],
                    "tags": ["orchestration"],
                },
            },
        },
        "downgrade_rules": {
            "docs_typo": {
                "tier": "light_docs",
                "confidence": 0.90,
                "all": {
                    "file_globs": ["docs/**/*.md", "*.md"],
                    "keywords_any": ["typo", "spelling", "grammar", "formatting"],
                },
                "deny_tags": ["security", "release", "architecture", "code_review"],
            },
            "readonly_summary": {
                "tier": "light_readonly",
                "confidence": 0.88,
                "all": {
                    "tool_access": "read_only",
                    "keywords_any": ["summarize", "extract", "list", "inspect"],
                },
                "max_body_chars": 6000,
                "deny_tags": ["security", "legal", "release", "code_review"],
            },
        },
    }


def merged_task_routing_config(
    model_set: ModelSet | None = None, user_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = _deep_merge(default_task_routing_config(), getattr(model_set, "task_routing", {}) or {})
    user_task = {}
    if isinstance(user_config, dict):
        agency = user_config.get("agency") if isinstance(user_config.get("agency"), dict) else {}
        models = agency.get("models") if isinstance(agency.get("models"), dict) else {}
        user_task = (
            models.get("task_routing") if isinstance(models.get("task_routing"), dict) else {}
        )
    if user_task:
        cfg = _deep_merge(cfg, user_task)
    return cfg


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def route_task_model(
    context: TaskRoutingContext,
    *,
    model_set: ModelSet | None = None,
    user_config: dict[str, Any] | None = None,
    preflight_fn: PreflightFn | None = None,
) -> ModelRouteDecision:
    try:
        model_set = model_set or load_model_set(DEFAULT_MODEL_SET)
        cfg = merged_task_routing_config(model_set, user_config)
        preflight = preflight_fn or (lambda p, m: preflight_provider_model(provider=p, model=m))
        return _route(context, cfg, preflight)
    except Exception as exc:
        health = provider_health_ok(provider=SAFE_PROVIDER, model=SAFE_MODEL).as_dict()
        return ModelRouteDecision(
            provider=SAFE_PROVIDER,
            model=SAFE_MODEL,
            tier=SAFE_TIER,
            family=None,
            source="default_safe",
            confidence=0.0,
            reasons=[f"classifier_error: {type(exc).__name__}"],
            matched_rules=[],
            risk_tags=["classifier_error"],
            preflight=health,
        )


def _route(
    context: TaskRoutingContext, cfg: dict[str, Any], preflight: PreflightFn
) -> ModelRouteDecision:
    default = cfg.get("default") if isinstance(cfg.get("default"), dict) else {}
    safe_provider = str(default.get("provider") or SAFE_PROVIDER)
    safe_model = str(default.get("model") or SAFE_MODEL)
    safe_tier = str(default.get("tier") or SAFE_TIER)
    if not bool(cfg.get("enabled", True)):
        health = preflight(safe_provider, safe_model)
        return _safe_default_decision(
            cfg,
            safe_provider,
            safe_model,
            safe_tier,
            "default_safe",
            1.0,
            ["task routing disabled"],
            [],
            [],
            health,
        )

    risk_tags, matched, reasons = classify_escalation(context, cfg)
    if risk_tags:
        health = preflight(safe_provider, safe_model)
        return _safe_default_decision(
            cfg,
            safe_provider,
            safe_model,
            safe_tier,
            "escalation",
            1.0,
            reasons,
            matched,
            risk_tags,
            health,
        )

    rule = match_downgrade_rule(context, cfg)
    min_conf = float((cfg.get("classifier") or {}).get("downgrade_min_confidence", 0.85))
    if not rule or rule[2] < min_conf:
        health = preflight(safe_provider, safe_model)
        reason = (
            "no confident low-risk allowlist rule matched"
            if not rule
            else f"confidence {rule[2]:.2f} below threshold {min_conf:.2f}"
        )
        return _safe_default_decision(
            cfg,
            safe_provider,
            safe_model,
            safe_tier,
            "default_safe",
            rule[2] if rule else 0.5,
            [reason],
            [rule[0]] if rule else [],
            [],
            health,
        )

    rule_id, tier_name, confidence = rule
    tier_cfg = (cfg.get("tiers") or {}).get(tier_name) or {}
    provider = str(tier_cfg.get("provider") or safe_provider)
    model = str(tier_cfg.get("model") or safe_model)
    health = preflight(provider, model)
    if health.ok:
        return _decision(
            provider,
            model,
            tier_name,
            "task_rule",
            confidence,
            [f"matched low-risk rule {rule_id}"],
            [rule_id],
            [],
            health,
        )

    safe_health = preflight(safe_provider, safe_model)
    return _safe_default_decision(
        cfg,
        safe_provider,
        safe_model,
        safe_tier,
        "health_fallback",
        confidence,
        [f"candidate {provider}/{model} failed preflight: {health.category}"],
        [rule_id],
        [],
        safe_health,
        fallback_used=True,
    )


def _safe_default_decision(
    cfg: dict[str, Any],
    provider: str,
    model: str,
    tier: str,
    source: str,
    confidence: float,
    reasons: list[str],
    matched: list[str],
    risks: list[str],
    health: ProviderHealthResult,
    *,
    fallback_used: bool = False,
) -> ModelRouteDecision:
    if _block_if_safe_default_unhealthy(cfg) and not health.ok:
        return ModelRouteDecision(
            provider=provider,
            model=model,
            tier=tier,
            family=None,
            source="blocked",
            confidence=confidence,
            reasons=[*reasons, f"safe default preflight failed: {health.category}"],
            matched_rules=matched,
            risk_tags=sorted({*risks, "provider_health"}),
            preflight=health.as_dict(),
            fallback_used=fallback_used,
            block_reason=f"provider-health: safe default {provider}/{model} failed preflight ({health.category})",
        )
    return _decision(
        provider,
        model,
        tier,
        source,
        confidence,
        reasons,
        matched,
        risks,
        health,
        fallback_used=fallback_used,
    )


def _block_if_safe_default_unhealthy(cfg: dict[str, Any]) -> bool:
    health_cfg = cfg.get("health") if isinstance(cfg.get("health"), dict) else {}
    return bool(health_cfg.get("block_if_safe_default_unhealthy", True))


def _decision(
    provider: str,
    model: str,
    tier: str,
    source: str,
    confidence: float,
    reasons: list[str],
    matched: list[str],
    risks: list[str],
    health: ProviderHealthResult,
    *,
    fallback_used: bool = False,
) -> ModelRouteDecision:
    return ModelRouteDecision(
        provider=provider,
        model=model,
        tier=tier,
        family=None,
        source=source,
        confidence=confidence,
        reasons=reasons,
        matched_rules=matched,
        risk_tags=risks,
        preflight=health.as_dict(),
        fallback_used=fallback_used,
    )


def classify_escalation(
    context: TaskRoutingContext, cfg: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    text = f"{context.title}\n{context.body}".casefold()
    tags = {
        str(t).strip().lower()
        for t in [*context.labels, *context.metadata.get("risk_tags", [])]
        if str(t).strip()
    }
    matched: list[str] = []
    reasons: list[str] = []
    esc = cfg.get("escalation") if isinstance(cfg.get("escalation"), dict) else {}
    if context.assignee and context.assignee in set(esc.get("assignees") or []):
        tags.add("orchestration" if "orchestrator" in context.assignee else "senior_review")
        matched.append("assignee_escalation")
        reasons.append(f"assignee {context.assignee} requires safe default")
    keyword_rules = esc.get("keyword_rules") if isinstance(esc.get("keyword_rules"), dict) else {}
    for rule_id, rule in keyword_rules.items():
        if not isinstance(rule, dict):
            continue
        needles = [str(x).casefold() for x in rule.get("any", [])]
        if any(n and n in text for n in needles):
            matched.append(str(rule_id))
            for tag in rule.get("tags", []):
                tags.add(str(tag).lower())
            reasons.append(f"matched escalation rule {rule_id}")
    classifier = cfg.get("classifier") if isinstance(cfg.get("classifier"), dict) else {}
    if context.prior_failures >= _int(classifier.get("repeated_failure_threshold"), 1):
        tags.add("repeated_failure")
        matched.append("repeated_failure")
        reasons.append("prior failed/blocked/timed-out run requires safe default")
    if len(context.parents) >= _int(classifier.get("long_context_parent_threshold"), 3):
        tags.add("long_context")
        matched.append("long_context_parents")
        reasons.append("many parent handoffs require safe default")
    if len(context.body) >= _int(classifier.get("long_context_body_chars"), 12000):
        tags.add("long_context")
        matched.append("long_context_body")
        reasons.append("large task body requires safe default")
    if _looks_ambiguous(context):
        tags.add("ambiguous_requirements")
        matched.append("ambiguous_requirements")
        reasons.append("requirements appear ambiguous or missing acceptance criteria")
    force_tags = {str(t).lower() for t in esc.get("tags", [])} or {
        "security",
        "privacy",
        "compliance",
        "legal",
        "architecture",
        "api_design",
        "system_design",
        "release",
        "deployment",
        "destructive_change",
        "code_review",
        "qa_signoff",
        "ambiguous_requirements",
        "long_context",
        "repeated_failure",
        "orchestration",
    }
    risks = sorted(tags.intersection(force_tags) or tags.intersection({"senior_review"}))
    return risks, matched, reasons or (["explicit risk tag requires safe default"] if risks else [])


def _looks_ambiguous(context: TaskRoutingContext) -> bool:
    body = context.body.strip().casefold()
    title = context.title.strip().casefold()
    if not body and any(w in title for w in ("fix", "implement", "update", "work")):
        return True
    return any(
        phrase in body
        for phrase in ("tbd", "unclear", "figure out", "missing context", "needs clarification")
    )


def match_downgrade_rule(
    context: TaskRoutingContext, cfg: dict[str, Any]
) -> tuple[str, str, float] | None:
    rules = cfg.get("downgrade_rules") if isinstance(cfg.get("downgrade_rules"), dict) else {}
    text = f"{context.title}\n{context.body}".casefold()
    tags = {
        str(t).lower()
        for t in [*context.labels, *context.metadata.get("risk_tags", [])]
        if str(t).strip()
    }
    best: tuple[str, str, float] | None = None
    for rule_id, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        if tags.intersection({str(t).lower() for t in rule.get("deny_tags", [])}):
            continue
        if rule.get("max_body_chars") is not None and len(context.body) > _int(
            rule.get("max_body_chars"), 0
        ):
            continue
        all_cfg = rule.get("all") if isinstance(rule.get("all"), dict) else {}
        kw = [str(k).casefold() for k in all_cfg.get("keywords_any", [])]
        if kw and not any(k in text for k in kw):
            continue
        tool_access = all_cfg.get("tool_access")
        if tool_access and str(context.metadata.get("tool_access") or "") != str(tool_access):
            continue
        globs = [str(g) for g in all_cfg.get("file_globs", [])]
        if globs and not _body_mentions_file_glob(context.body, globs):
            continue
        candidate = (
            str(rule_id),
            str(rule.get("tier") or SAFE_TIER),
            float(rule.get("confidence") or 0.0),
        )
        if best is None or candidate[2] > best[2]:
            best = candidate
    return best


def _body_mentions_file_glob(body: str, globs: list[str]) -> bool:
    lowered = body.casefold()
    if not globs:
        return True
    for glob in globs:
        if glob.endswith("*.md") and re.search(r"[\w./-]+\.md\b", lowered):
            return True
        if glob.casefold().strip("*") and glob.casefold().strip("*") in lowered:
            return True
    return False
