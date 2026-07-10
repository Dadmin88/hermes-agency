# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Use [GitHub Security Advisories](https://github.com/DeployFaith/Hermes_Agency/security/advisories/new) to report vulnerabilities privately.

Please include:

1. Description of the vulnerability
2. Steps to reproduce
3. Affected component(s)
4. Impact assessment (if possible)

## Response Timeline

- **Acknowledgement**: within 48 hours
- **Initial assessment**: within 7 days
- **Fix or mitigation**: depends on severity, typically within 30 days

## Security Boundaries

Hermes Agency has several distinct trust boundaries. Understanding them helps you assess impact and report issues accurately.

### Pool Manager

The pool manager routes tasks to staff agents. It can attempt to wake offline agents and queue tasks persistently. A compromised pool manager could misroute tasks or exhaust agent wake budgets.

### Remote Task Execution

Staff agents execute delegated tasks with access to their configured tools and model providers. Task payloads travel over the P2P transport layer. A malicious task payload could attempt to exploit an agent's tool set or model integration, so remote execution defaults to disabled and tool access defaults to `safe`.

### Keryx Relay and Registry

Keryx is the primary transport. Relay and registry services route encrypted P2P traffic and map capabilities/skills to peers. A compromised relay or registry could cause traffic analysis, misrouting, or service disruption, but should not grant plaintext task visibility when end-to-end transport encryption is intact.

### Vendored Python SDK vs Runtime Binaries

The Keryx Python SDK is vendored in this repository at `src/keryx/`. Keryx daemon/relay/registry binaries are external runtime components and must be installed, built, pinned, and monitored by the deployment. Do not commit runtime binaries, sockets, logs, private endpoints, or local daemon paths.

### Legacy AgentAnycast Fallback

`src/agentanycast/` is retained for legacy rollback/fallback deployments. Do not use AgentAnycast as the default for new security reviews unless `agency.transport_backend: agentanycast` is explicitly selected. Vulnerabilities in the fallback path are still in scope when that backend is supported.

### Model and Tool Access

Each agent has a configured model set and tool set. The agency restricts which tools and models an agent can access based on its role and configuration. An agent should not be able to escalate beyond its assigned tool or model scope.

## Transport Layer Security

Hermes Agency's primary transport path uses Keryx for encrypted peer communication and relay/registry-backed discovery. Configure Keryx endpoints under `agency.keryx.*` or with `HERMES_KERYX_*` / `KERYX_*` environment variables. Keep endpoint examples generic in committed docs and never publish private relay addresses, peer IDs, tokens, or local paths.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We will work with you to understand and address the issue before any public disclosure.

## Recognition

We appreciate responsible disclosure and will credit reporters (with permission) in release notes.
