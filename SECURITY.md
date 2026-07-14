# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| latest | Yes |

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Use [GitHub Security Advisories](https://github.com/DeployFaith/Hermes_Agency/security/advisories/new) to report vulnerabilities privately. Include:

1. A description of the vulnerability
2. Deterministic reproduction steps
3. The affected component and version or commit
4. The expected impact
5. Any known mitigation

## Response Timeline

- **Acknowledgement:** within 48 hours
- **Initial assessment:** within 7 days
- **Fix or mitigation:** depends on severity, typically within 30 days

## Security Boundaries

Hermes Agency spans several processes and trust boundaries. Reports should identify which boundary is crossed.

### Hermes Agency plugin and pool

The Agency plugin and pool manager route tasks to staff agents, attempt wake for offline specialists, and queue work persistently. A compromised pool manager could misroute tasks or exhaust agent wake budgets. Lifecycle tools must validate profile names and process ownership before signaling host processes.

### Remote task execution

Staff agents execute delegated tasks with access to their configured tools and model providers. Defaults are conservative:

- `allow_remote_tasks: false`
- `incoming.tool_access: safe`
- empty peer allowlist means deny (unless explicitly configured otherwise)

Incoming work must pass allowlist and trust verification. Prefer transport-authenticated sender identity over arbitrary task metadata.

### Keryx transport (primary)

Keryx provides daemon, relay, registry, mailbox, routing, claim-next worker dispatch, and terminal result/artifact return. Peer communication uses encrypted transport primitives owned by the Keryx runtime. Compromising the relay or registry could allow traffic analysis or service disruption; see the [hermes-keryx](https://github.com/DeployFaith/hermes-keryx) security guidance for runtime-specific details.

### AgentAnycast (legacy fallback)

AgentAnycast under `src/agentanycast/` is retained for explicit legacy/fallback deployments only (`agency.transport_backend: agentanycast`). Do not treat it as the recommended production path. Legacy daemon download/verification behavior, when used, must follow AgentAnycast verification guidance.

### Management endpoints

Pool management HTTP and local APIs should bind to loopback by default. Non-loopback binds require authentication (for example `HERMES_POOL_TOKEN`). State-changing endpoints must require authentication.

### Model and tool access

### Hermes Fabric

### Outbound remote content

Remote-visible progress, artifacts, and error summaries should not include secrets, credential-bearing URLs, private keys, or local absolute paths. Detailed raw diagnostics stay local.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure) and will work with reporters before public disclosure.

## Recognition

We appreciate responsible disclosure and will credit reporters, with permission, in release notes.
