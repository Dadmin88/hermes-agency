# Agency Smart Model Routing Design

## Goal

Hermes Agency should choose an appropriate model per task/card/session without requiring Kyle to bulk-edit every `agency-*` profile when the work changes. The safe baseline remains provider `openai-codex` with model `gpt-5.5`; any uncertainty, missing health signal, or elevated-risk task must use that baseline instead of silently drifting to cheaper or broken providers.

## Current constraints

- Static `hermes-agency/model_sets/*.yaml` presets resolve profile families to provider/model pairs and can safely write profile `config.yaml` files, but they are coarse profile-level defaults.
- Existing worker execution is profile/session oriented. The smart router should pass a model override into the task/session spawn path, not continuously mutate installed profile configs.
- Provider failures such as quota exhaustion, auth errors, and outages must be treated as infrastructure state. A lower tier is usable only after preflight says that exact provider/model is healthy.
- The default packaged model set is `openai-codex-only`; `openai-codex/gpt-5.5` is the required safe fallback for all Agency workers.

## Design summary

Add an Agency task-aware model router that runs immediately before worker/session creation. It classifies the task, selects a routing tier from config, preflights the selected provider/model, and returns an explicit `ModelRouteDecision` to the dispatcher/pool sender. The decision is applied as a per-run model override and recorded in Kanban metadata/logs.

The router is conservative:

1. Start with `openai-codex/gpt-5.5` as the default candidate.
2. Classify the task from card title/body, assignee role, requested skills, metadata, prior run history, file/change hints, and explicit risk tags.
3. Escalate to `gpt-5.5` if any high-risk or uncertainty trigger is present.
4. Downgrade only when the classifier reaches a configured confidence threshold and all matched rules are allowlisted low-risk rules.
5. Preflight the selected provider/model.
6. If preflight fails for a downgrade candidate, fall back to `openai-codex/gpt-5.5` if healthy; otherwise block dispatch with a provider-health reason rather than spawning failing workers.

## Runtime component boundary

Proposed module structure:

```text
hermes-agency/
  smart_model_router.py       # pure decision engine and classifier glue
  provider_preflight.py       # health classification and provider/model smoke checks
  model_sets.py               # extend schema loading/validation for task routing sections
  pool/                       # apply per-task model override when waking/spawning profiles
  kanban_bridge.py            # attach route metadata to card/run/comment metadata
  tests/test_smart_model_router.py
  tests/test_provider_preflight.py
```

The router should be mostly pure and testable. Runtime integrations should be thin adapters that provide task context and consume the decision.

## Decision object

Use an explicit serialisable decision object:

```python
@dataclass(frozen=True)
class ModelRouteDecision:
    provider: str
    model: str
    tier: str
    family: str | None
    source: str                  # default_safe | task_rule | escalation | health_fallback | blocked
    confidence: float
    reasons: list[str]
    matched_rules: list[str]
    risk_tags: list[str]
    preflight: dict[str, Any]
    fallback_used: bool = False
    block_reason: str | None = None
```

The dispatcher must not infer routing from profile config after this point. If a decision is usable, it becomes the worker run/session model override. If `block_reason` is set, the dispatcher should block the task/system queue with that reason.

## Classification inputs

The classifier should consume a normalized `TaskRoutingContext`:

- Kanban: task id, title, body, assignee, board, priority, parents, child count, comments, prior attempts, run outcome history.
- Agency metadata: target profile, requested skills, target department, correlation id, originating peer, explicit risk tags.
- Delegation/session: user prompt, context packet, tool-access mode, allowed paths, requested validation.
- Code hints when available: changed-file globs, diff stats, destructive command hints, release/deploy keywords.
- Profile metadata: staff category/model family from default staff manifest.

Do not include secrets or raw environment dumps in classifier logs or model-route metadata.

## Escalation rules

Any of these conditions forces provider `openai-codex`, model `gpt-5.5`:

- Security, privacy, compliance, legal, auth, credentials, secrets, permission, or threat-model work.
- Architecture, system design, API design, cross-module boundaries, or long-term maintainability decisions.
- Release, deployment, migration, rollback, production incident, infrastructure, or data-loss risk.
- Destructive changes: deletes, rewrites, migrations, bulk profile edits, branch/history operations, or irreversible external side effects.
- Code review, QA signoff, final approval, merge readiness, or reviewer verdict tasks.
- Ambiguous requirements, missing acceptance criteria, conflicting instructions, or unclear target path/scope.
- Long-context synthesis: many parent handoffs, large diffs, broad repo scans, multi-document summaries, or tasks likely to exceed the configured context threshold.
- Repeated failures: any prior failed/blocked/timed-out run for the same task, provider failure recovery, or explicit retry/re-review language.
- Orchestration/decomposition tasks that create or route work for other agents.
- Any classifier confidence below the downgrade threshold.

Escalation is sticky for the run. Once a task escalates, later low-risk matches must not downgrade it.

## Low-risk downgrade rules

A task may use a cheaper/lighter tier only when all of the following are true:

- No escalation trigger matched.
- The task matches at least one positive low-risk rule.
- Classifier confidence is at or above `downgrade_min_confidence`.
- The selected tier and exact provider/model pass preflight.
- The task has not failed previously.
- The requested tools and paths are non-destructive.

Examples of eligible low-risk work:

- Simple formatting, typo fixes, or copy edits in non-sensitive docs.
- Summarizing one small non-sensitive document.
- Creating boilerplate tickets or low-stakes checklists from clear input.
- Read-only inspections that do not produce approval/signoff decisions.
- Trivial test fixture cleanup with narrow file scope and no release/security implications.

Downgrade rules should be explicit allowlists, not broad negative matching. For example, `docs_typo` may downgrade; `not security` must not be enough.

## Provider health guard

Provider/model health must be checked at route time for any non-safe candidate and cached briefly to avoid excessive probes.

Required behavior:

1. Preflight the exact provider/model selected by task rules.
2. If downgrade preflight fails, classify the failure with `provider_preflight.classify_provider_failure` style categories: `quota_exhausted`, `auth_failed`, `provider_unavailable`, or `unknown_provider_failure`.
3. Try the safe fallback `openai-codex/gpt-5.5`.
4. If the safe fallback is healthy, use it and record `source=health_fallback` plus the failed candidate and preflight category.
5. If the safe fallback is unhealthy because of quota/auth/outage, block dispatch/systemically instead of cycling workers into predictable failure.

Recommended preflight levels:

- `cached`: use recent health result inside TTL.
- `config`: verify provider/model exists in catalog and required provider config is present.
- `smoke`: optional one-token/no-op provider call for dispatch batches or after prior failures.

## Auditability

Every routed Kanban run should record compact routing metadata. Suggested metadata shape:

```json
{
  "agency_model_route": {
    "provider": "openai-codex",
    "model": "gpt-5.5",
    "tier": "safe_default",
    "source": "escalation",
    "confidence": 0.91,
    "matched_rules": ["architecture_keyword", "assignee_senior_review"],
    "risk_tags": ["architecture"],
    "reasons": ["Architecture/design work must use safe fallback"],
    "fallback_used": false,
    "preflight": {"ok": true, "category": "ok"}
  }
}
```

Kanban views and logs should show at least `provider/model`, `tier`, `source`, and a one-line reason. Full prompts, secrets, raw provider errors, and large classifier traces should not be persisted.

## Config shape

Keep existing profile-level model set fields for installed-profile defaults, and add a task-routing section under `agency.models.task_routing` or under model-set YAML. User config should override packaged preset routing rules.

Example:

```yaml
agency:
  models:
    active_set: openai-codex-only
    task_routing:
      enabled: true
      mode: conservative
      default:
        provider: openai-codex
        model: gpt-5.5
        tier: safe_default
      health:
        preflight: cached
        cache_ttl_seconds: 300
        smoke_on_prior_failure: true
        block_if_safe_default_unhealthy: true
      classifier:
        downgrade_min_confidence: 0.85
        uncertain_goes_to_default: true
        long_context_parent_threshold: 3
        long_context_body_chars: 12000
        repeated_failure_threshold: 1
      tiers:
        safe_default:
          provider: openai-codex
          model: gpt-5.5
          reason: Safe fallback for all Agency workers.
        light_docs:
          provider: openai-codex
          model: gpt-5.5
          reason: Placeholder tier; may be changed only after provider/model preflight and policy approval.
        light_readonly:
          provider: openai-codex
          model: gpt-5.5
          reason: Placeholder tier; may be changed only after provider/model preflight and policy approval.
      escalation:
        force_tier: safe_default
        tags:
          - security
          - privacy
          - compliance
          - legal
          - architecture
          - api_design
          - system_design
          - release
          - deployment
          - destructive_change
          - code_review
          - qa_signoff
          - ambiguous_requirements
          - long_context
          - repeated_failure
          - orchestration
        assignees:
          - agency-orchestrator
          - agency-software-architect
          - agency-systems-architect
          - agency-security-reviewer
          - agency-code-reviewer
          - agency-release-manager
        keyword_rules:
          architecture_keyword:
            any: [architecture, design, boundary, module, dependency, pattern]
            tags: [architecture]
          destructive_keyword:
            any: [delete, destructive, migration, rollback, rewrite, production]
            tags: [destructive_change]
      downgrade_rules:
        docs_typo:
          tier: light_docs
          confidence: 0.90
          all:
            file_globs: ["docs/**/*.md", "*.md"]
            keywords_any: [typo, spelling, grammar, formatting]
          deny_tags: [security, release, architecture, code_review]
        readonly_summary:
          tier: light_readonly
          confidence: 0.88
          all:
            tool_access: read_only
            keywords_any: [summarize, extract, list, inspect]
          max_body_chars: 6000
          deny_tags: [security, legal, release, code_review]
```

The packaged `openai-codex-only` preset can initially define all tiers as `openai-codex/gpt-5.5`. That preserves Kyle's corrected default while allowing the router, metadata, health guard, and tests to land safely. Cheaper tiers can then be introduced intentionally in `balanced` or user presets after provider health and pricing are validated.

## Integration flow

1. Dispatcher or pool sender builds `TaskRoutingContext` before spawning a worker.
2. Router loads merged config: active model set plus user `agency.models.task_routing` overrides.
3. Router evaluates escalation rules first.
4. Router evaluates downgrade allowlist rules only if no escalation matched.
5. Router preflights selected provider/model.
6. Router returns `ModelRouteDecision`.
7. Spawn path passes `model={provider, model}` as a per-run/session override without editing profile config.
8. Kanban run/task metadata stores the compact route audit record.
9. Worker receives normal task context; it does not need to know whether the model came from profile config or router override.

## Failure behavior

- Classifier error: route to `openai-codex/gpt-5.5`, `source=default_safe`, reason `classifier_error`.
- Unknown provider/model in config: do not use it; fall back to safe default if healthy and log validation error.
- Downgrade provider quota/auth/outage: fall back to safe default if healthy.
- Safe default quota/auth/outage: block dispatch with provider-health blocker; do not repeatedly spawn workers.
- Contradictory rules: escalation wins.
- Missing task metadata: safe default.

## Implementation acceptance criteria

- A smart-router module exists with unit-tested pure functions for context normalization, escalation detection, downgrade rule matching, preflight fallback, and decision serialization.
- Existing profile-level model sets continue to validate and apply without requiring smart routing.
- The default behavior with no task-routing config, disabled task routing, classifier uncertainty, or config errors is `openai-codex/gpt-5.5`.
- Router decisions are applied per task/card/session and do not mutate installed `agency-*` profile `config.yaml` files during normal dispatch.
- Kanban run metadata or comments record selected provider/model, tier, source, matched rule ids, risk tags, preflight category, and concise reason.
- Security, architecture, release, destructive-change, code-review, ambiguous, long-context, orchestration, and repeated-failure fixtures all route to `openai-codex/gpt-5.5`.
- Low-risk downgrade fixtures route to configured lighter tiers only when all allowlist and confidence requirements are met.
- A failed downgrade preflight falls back to `openai-codex/gpt-5.5` when healthy.
- An unhealthy safe default blocks dispatch with a systemic provider-health reason instead of launching workers.
- No router log, metadata entry, test fixture, or AgentCard leaks secrets, raw credentials, private peer ids, gateway logs, or local machine-specific paths.

## Test acceptance criteria

Add tests covering:

- `test_default_uncertain_routes_to_gpt55`.
- `test_disabled_router_routes_to_profile_or_safe_default_without_config_mutation`.
- `test_architecture_security_release_review_and_destructive_tasks_escalate`.
- `test_ambiguous_requirements_and_repeated_failures_escalate`.
- `test_low_risk_docs_typo_can_downgrade_when_confident_and_healthy`.
- `test_low_risk_rule_denied_by_security_tag_escalates`.
- `test_failed_downgrade_preflight_uses_safe_default`.
- `test_failed_safe_default_preflight_blocks_dispatch`.
- `test_route_metadata_is_compact_and_secret_safe`.
- `test_model_set_validation_rejects_unknown_task_routing_tier_or_provider`.
- `test_dispatch_passes_model_override_per_run_without_writing_profile_config`.
- `test_kanban_metadata_contains_provider_model_reason_and_preflight_category`.

Recommended validation commands after implementation:

```bash
python -m pytest hermes-agency/tests/test_model_sets.py -q
python -m pytest hermes-agency/tests/test_smart_model_router.py -q
python -m pytest hermes-agency/tests/test_provider_preflight.py -q
make test-agency
make lint-agency
```
