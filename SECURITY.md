# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please use [GitHub Security Advisories](https://github.com/DeployFaith/Hermes_Agency/security/advisories/new) to report vulnerabilities privately.

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

Staff agents execute delegated tasks with access to their configured tools and model providers. Task payloads travel over the P2P transport layer (Noise_XX encrypted). A malicious task payload could attempt to exploit an agent's tool set or model integration.

### Relay and Registry

The relay server forwards encrypted P2P messages between peers. It cannot read message content. The registry maps skills to peer IDs. Compromising the relay or registry could allow traffic analysis or service disruption but not plaintext message disclosure.

### Daemon Downloads

The AgentAnycast Go daemon binary is auto-downloaded on first run. The SDK verifies the binary before execution. A compromised download source could serve a malicious daemon. See the AgentAnycast documentation for verification details.

### Model and Tool Access

Each agent has a configured model set and tool set. The agency restricts which tools and models an agent can access based on its role and configuration. An agent should not be able to escalate beyond its assigned tool or model scope.

## Transport Layer Security

The AgentAnycast P2P layer uses end-to-end encryption (Noise_XX protocol + NaCl box) for all peer communication. The relay server cannot read message content. See the [AgentAnycast architecture documentation](https://github.com/AgentAnycast/agentanycast/blob/main/docs/architecture.md) for details.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We will work with you to understand and address the issue before any public disclosure.

## Recognition

We appreciate responsible disclosure and will credit reporters (with permission) in release notes.
