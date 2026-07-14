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

### Pool and Management Services

The pool manager can wake and stop staff processes, queue tasks, and route work. Local HTTP services bind to loopback by default. State-changing pool endpoints require `HERMES_POOL_TOKEN`; when the token is not configured, mutations fail closed rather than running unauthenticated. Exposing a management service beyond loopback requires explicit network controls in addition to application authentication.

### Remote Task Execution

Remote execution is disabled by default (`allow_remote_tasks: false`). When enabled, incoming senders are checked against the configured peer and trust policy before acceptance. Recovered queued tasks are checked again before execution so revoking trust also affects persisted work. Tool access defaults to the safe policy and subprocess processing requires an explicit opt-in plus the configured minimum sender trust.

Remote prompts and model output remain untrusted data. Operators should grant only the tools and credentials required by each profile and should not treat transport authentication as prompt-safety enforcement.

### Configuration and Profile Files

Hermes profile names are validated before path construction. Fabric model-set application resolves the configured profiles root, rejects path escapes including symlinked profile directories outside that root, and writes profile configuration atomically. Profile configuration and model-set files must not contain credentials.

### Relay and Registry

Keryx is the primary transport. The Python SDK in this repository communicates with the external `keryxd` runtime; the Rust daemon, relay, registry, deployment topology, and migration tooling are maintained in the separate `hermes-keryx` repository. Security claims about Keryx wire encryption, relay visibility, identity verification, and deployment hardening must be evaluated against the exact external runtime version and configuration in use. This repository does not make a stronger cryptographic guarantee than that runtime proves.

AgentAnycast remains a legacy/fallback transport under `src/agentanycast/`. Its Noise and NaCl behavior applies only when that backend is explicitly selected and must not be used as evidence for Keryx deployments.

### External Runtime Binaries

Hermes Agency does not vendor the Keryx Rust binaries. Obtain `keryxd` and `keryx-relay` from the separately maintained Keryx release or build process, verify the release provenance expected by that project, and run them with least privilege. Legacy AgentAnycast binary-download behavior is confined to the fallback SDK and is not the Keryx installation path.

### Hermes Fabric

Hermes Fabric is a separate operator interface. Its current Agency roster and dispatch store are instance-global, so those routes require an instance administrator. Future company-scoped Agency state must enforce company and actor authorization before access. The default Agency dispatch client is unconfigured/dry-run; dry-run records are not proof of live end-to-end dispatch.

### Models, Tools, and Secrets

Each profile has a configured model and tool scope. Secret values belong in the supported credential stores or environment configuration, never in AgentCards, model-set YAML, public task metadata, documentation, logs, or test fixtures. Reports involving credential disclosure should include redacted evidence only.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure) and will work with reporters before public disclosure.

## Recognition

We appreciate responsible disclosure and will credit reporters, with permission, in release notes.
