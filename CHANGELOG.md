# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-03-21

### Added

- Claude Agent SDK adapter (`agentanycast[claude]`) — expose prompt-based agents over P2P
- AWS Strands Agents adapter (`agentanycast[strands]`) — bridge Strands agents to P2P
- Proto stubs updated with OpenTelemetry trace context fields for distributed tracing

## [0.6.0] - 2026-03-20

### Added

- MCP server mode with stdio and HTTP transports
- AGNTCY Directory client for agent discovery via the AGNTCY ecosystem
- Streaming support for chunked artifact delivery
- `did:web` and `did:dns` DID method support alongside existing `did:key`
- `BaseAdapter` ABC for consistent adapter authoring with auto-card generation

### Changed

- Adapter robustness improvements and MCP server correctness fixes

## [0.5.0] - 2026-03-19

### Added

- Google ADK adapter (`agentanycast[google-adk]`)
- OpenAI Agents SDK adapter (`agentanycast[openai-agents]`)
- A2A v1.0 protocol compatibility layer (`task_to_a2a_json` / `task_from_a2a_json`)
- OASF record conversion (`card_to_oasf_record` / `card_from_oasf_record`)
- AI discoverability metadata for package indexes

## [0.4.0] - 2026-03-19

### Added

- CrewAI adapter (`agentanycast[crewai]`) — serve CrewAI crews as P2P agents
- LangGraph adapter (`agentanycast[langgraph]`) — serve compiled graphs as P2P agents
- Click-based CLI with `demo`, `discover`, `send`, `status`, and `info` commands
- Integration test framework with Docker Compose E2E tests

## [0.3.0] - 2026-03-18

### Added

- HTTP Bridge support — `url=` parameter in `send_task()` for interop with standard HTTP A2A agents
- MCP tool mapping (`mcp_tools_to_agent_card`, `mcp_tool_to_skill`, `skill_to_mcp_tool`)
- DID support (`peer_id_to_did_key`, `did_key_to_peer_id`)
- PyPI release workflow with OIDC Trusted Publishing

## [0.2.0] - 2026-03-18

### Added

- Skill-based anycast discovery via `discover()` method
- Relay connection support for cross-network communication
- `connect_peer()` and `list_peers()` for peer management
- Real P2P task E2E tests over Noise-encrypted channels

## [0.1.0] - 2026-03-17

### Added

- `Node` class — async context manager for P2P agent communication
- `AgentCard` and `Skill` dataclasses for agent capability description
- `TaskHandle` for tracking outgoing tasks with `wait()` support
- `IncomingTask` for receiving and responding to tasks (`complete()`, `fail()`, `update_status()`)
- Automatic daemon lifecycle management (start, stop, health check)
- Auto-download of daemon binary when not provided
- gRPC client for SDK-daemon communication over Unix domain socket
- `home` parameter for running multiple nodes on the same machine
- Hello world example with server and client agents
- PEP 561 `py.typed` marker for type checking support
- CI pipeline with ruff lint, mypy type check, and multi-version pytest

[0.7.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.7.0
[0.6.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.6.0
[0.5.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.5.0
[0.4.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.4.0
[0.3.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.3.0
[0.2.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.2.0
[0.1.0]: https://github.com/AgentAnycast/agentanycast-python/releases/tag/v0.1.0
