# Hermes Agency — Repo Guidance

**Primary component:** The Hermes Agency plugin (`hermes-agency/`) is the main deliverable of this repository. It provides the full 83-agent roster, orchestration, Kanban sync, team context, proactive workflows, and P2P integration for Hermes profiles.

**SDK dependency:** The AgentAnycast Python SDK lives in `src/agentanycast/`. It is the foundational P2P layer (daemon management, Node API, A2A protocol, adapters). Hermes Agency depends on it (lazy imports where possible).

**Key files**
- `hermes-agency/AGENTS.md` — Detailed contributor notes, safety rules, test commands, and plugin shape.
- `hermes-agency/plugin.yaml` — Plugin declaration.
- `README.md` — Public-facing documentation (Hermes Agency first).
- `pyproject.toml` — SDK package metadata + Hermes Agency context.

**Contribution flow**
1. Read `hermes-agency/AGENTS.md` first.
2. All changes to the plugin must respect lazy SDK imports and `agency.enabled` gating.
3. Use `make test-agency`, `make lint-agency`, `make integration-agency` for validation.
4. Tenant = default, team context filter = agency-only.

**Delegation**
Offline agents in the roster remain valid targets. `agency_pool_send` / orchestrator routing will attempt wake + persistent queue.

See the full roster in the Hermes Agency team context for skill-matched delegation.
