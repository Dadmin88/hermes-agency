# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Use [GitHub Security Advisories](https://github.com/DeployFaith/Hermes_Agency/security/advisories/new) to report vulnerabilities privately.

Please include:

1. Description of the vulnerability
2. Steps to reproduce
3. Affected component(s)
4. Impact assessment, if possible

## Response Timeline

- **Acknowledgement**: within 48 hours
- **Initial assessment**: within 7 days
- **Fix or mitigation**: depends on severity, typically within 30 days

## Security Design

Hermes Agency uses a P2P runtime with end-to-end encrypted transport for agent communication. The relay layer should not be able to read message content.

The Hermes plugin is conservative by default:

- Plugin loading is opt-in through `plugins.enabled`.
- Runtime operation is gated by `agency.enabled`.
- Remote task execution defaults to safe behavior.
- AgentCards must not expose API keys, tokens, raw env vars, local daemon paths, Discord channel IDs, or profile-private data.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We will work with you to understand and address the issue before any public disclosure.

## Recognition

We appreciate responsible disclosure and will credit reporters, with permission, in release notes.
