---
name: mcp-server-deployment
description: "Build, patch, test, and deploy MCP servers/connectors for external clients such as ChatGPT Developer Mode, including HTTP transport, CORS, service management, and exposure checks."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [mcp, deployment, fastmcp, chatgpt, cors, systemd, tailscale]
    created_by: agent
---

# MCP Server Deployment

Use this skill when installing, modifying, or exposing an MCP server/connector for another client (ChatGPT Developer Mode, Claude Desktop, IDEs, local agents), especially when the work includes FastMCP, HTTP/SSE transport, CORS, systemd services, or Tailscale Funnel.

## Core workflow

1. **Inspect the existing server and tests first.** Identify transport creation, app lifecycle, tool registration/gating, and current schema tests before patching.
2. **Write or update tests before implementation when changing behavior.** Cover tool gating, tool schemas/descriptions, security-deny cases, HTTP health, CORS preflight, initialize, and tools/list.
3. **Preserve a minimal public tool surface.** Keep dangerous tools behind explicit environment gates; verify disabled tools are absent from `tools/list`, not just unusable when called.
4. **Add client-facing tool descriptions.** FastMCP exposes function docstrings as tool descriptions; every externally registered tool should have a concise, actionable docstring.
5. **Verify the ASGI lifecycle, not just routing.** If wrapping a FastMCP app in another Starlette app, preserve the underlying MCP app lifespan context or streamable HTTP sessions can fail at runtime.
6. **Verify with real HTTP requests.** Always exercise `GET /`, CORS `OPTIONS`, MCP `initialize`, and `tools/list` against the running process/service.
7. **Install under a supervisor.** Prefer a user-level systemd service for per-user connectors; verify `systemctl --user status`, enabled state, service environment, and restart behavior.
8. **Expose only after local verification.** For Funnel/proxy exposure, first prove loopback service health and CORS behavior locally, then configure public exposure and verify status.

## FastMCP / ChatGPT Developer Mode pitfalls

- **CORS is not the whole origin story.** Starlette `CORSMiddleware` adds browser CORS headers, but the MCP SDK may also enforce transport security checks. Configure FastMCP `transport_security` with the required `allowed_origins` and `allowed_hosts` when serving browser-based clients.
- **Wrapping FastMCP can break streamable HTTP.** `server.streamable_http_app()` owns a lifespan that initializes the streamable HTTP session manager. If mounting it under a wrapper Starlette app, set the wrapper's `lifespan` to the raw MCP app's `router.lifespan_context`.
- **Client `Accept` headers can be stricter than expected.** Some clients/probes send no `Accept` or `*/*`; the MCP SDK may return `406 Not Acceptable` unless `application/json` and/or `text/event-stream` is accepted. For compatibility shims, use a narrow middleware on the MCP path that supplies `Accept: application/json, text/event-stream` only when absent or wildcard.
- **Mounting route shape matters.** A common pattern is a wrapper Starlette app with `Route("/", health_root)` and `Mount("/", app=mcp_app)` so `GET /` is a simple health endpoint while `/mcp` continues to be handled by FastMCP.
- **Tailscale Funnel may be policy-blocked.** If `tailscale funnel <port>` says the node is not in the allowed Funnel node list, stop and report the exact admin-policy URL/error; do not claim the public URL is live until `tailscale funnel status` shows active config. If the user asks what to change, give a complete replacement `nodeAttrs` block or full policy file; do not hand-wave.
- **Foreground Funnel output is not persistence.** `sudo tailscale funnel <port>` without `--bg` can print “Available on the internet” and then exit on timeout without persisting config. Use `sudo tailscale funnel --bg <port>` for durable Serve/Funnel config, then verify with `tailscale funnel status` and `tailscale serve status --json`.
- **ChatGPT remote auth should be OAuth, not just raw bearer.** For ChatGPT MCP custom apps, implement OAuth discovery, authorization-code redirect, token exchange, and MCP bearer validation. Keep static bearer as an emergency/local fallback, but document ChatGPT setup as `Authentication: OAuth` + `User-Defined OAuth Client`.

## Verification checklist

- Tests pass for the edited server/test files.
- Service is `active (running)` and enabled if it should persist.
- `GET /` returns a stable JSON health body.
- CORS preflight from the target origin returns `200` with `access-control-allow-origin`.
- MCP `initialize` returns a valid JSON-RPC result with expected `serverInfo`.
- MCP `tools/list` returns exactly the intended tool set.
- Explicitly confirm dangerous/disabled tools are absent.
- Public exposure status is verified independently (`tailscale funnel status`, reverse proxy config, etc.).
- For OAuth-protected MCP connectors, discovery endpoints return expected issuer/authorization/token metadata, `/oauth/authorize` redirects with a one-time code, `/oauth/token` exchanges it once, `/mcp` rejects missing/invalid tokens with `401 WWW-Authenticate: Bearer`, and `/mcp initialize` succeeds with an OAuth bearer token.

## References

- `references/fastmcp-chatgpt-developer-mode.md` — concrete lessons from a hermes-gpt ChatGPT Developer Mode deployment, including FastMCP lifespan, CORS/transport security, Accept header compatibility, OAuth custom-app auth, and Tailscale Funnel policy/persistence handling.
