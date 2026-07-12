# Hermes Gateway Onboarding

Use this guide when a Hermes runtime should join Hermes Fabric as an external
`hermes_gateway` employee. This mirrors the OpenClaw gateway invite path, but
Hermes uses the generic agent invite/onboarding flow instead of the
OpenClaw-specific invite prompt endpoint.

## Choose The Adapter

Hermes Fabric ships both Hermes adapters as built-ins:

- `hermes_local` runs the local `hermes` CLI as a child process on the
  Hermes Fabric host.
- `hermes_gateway` calls an already-running Hermes API server over HTTP/SSE.

No Adapter manager installation is required for normal use. Adapter manager is
only needed when you intentionally install an external
`@hermes-fabric/hermes-fabric-adapter` package to override or shadow a built-in
adapter while developing the Hermes package. If the external override is paused
or removed, Hermes Fabric restores the built-in `hermes_local` / `hermes_gateway`
adapter.

## Required Credentials

Keep these credentials distinct:

- Hermes inference provider key: set at least one provider key for Hermes, such
  as `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `GEMINI_API_KEY`, `GOOGLE_API_KEY`, or `MISTRAL_API_KEY`.
- Hermes gateway key: set `API_SERVER_KEY` before starting Hermes. Hermes Fabric
  stores the same value as `agentDefaultsPayload.apiKey` so it can call Hermes.
- Hermes Fabric agent key: created after the board approves the join request and
  claimed once by the Hermes agent. Hermes uses this key as
  `HERMES_FABRIC_API_KEY` when it calls Hermes Fabric.

Do not reuse the Hermes gateway key as the Hermes Fabric agent key. The Hermes
gateway key authenticates Hermes Fabric-to-Hermes traffic; the claimed Hermes Fabric key
authenticates Hermes-to-Hermes Fabric traffic.

## Start Hermes Gateway

Install and configure Hermes first:

```sh
pip install hermes-agent
export OPENROUTER_API_KEY='<provider-key>'
export API_SERVER_KEY='<random-gateway-key>'
API_SERVER_ENABLED=true hermes gateway run --replace --accept-hooks
```

The default Hermes API server port is `8642`. For local loopback testing,
Hermes Fabric can usually store `http://127.0.0.1:8642` as the gateway URL. For
Docker, LAN, tailnet, or reverse-proxy setups, use a URL reachable by the
Hermes Fabric server process.

Plain HTTP is accepted for loopback. Non-loopback HTTP is denied by default in
the join flow; use HTTPS for real remote gateways. For private local
development only, the join payload can set
`dangerouslyAllowInsecureRemoteHttp: true`, and the smoke scripts expose the
same escape hatch as `HERMES_GATEWAY_ALLOW_INSECURE_HTTP=1`.

## Invite From Hermes Fabric

In the board UI:

1. Open the target company.
2. Use the add-agent button in the agent sidebar.
3. Generate an agent onboarding prompt/invite.
4. Give the generated onboarding text to the Hermes runtime.

The UI prompt points Hermes at the same machine-readable onboarding endpoints:

- `GET /api/invites/:token`
- `GET /api/invites/:token/onboarding`
- `GET /api/invites/:token/onboarding.txt`
- `GET /api/skills/index`
- `GET /api/skills/fabric`

For CLI-driven setup, create and inspect the invite directly:

```sh
pnpm hermes-fabric invite create --company-id <company-id> --payload-json '{"requestType":"agent"}'
pnpm hermes-fabric invite show <token>
pnpm hermes-fabric invite onboarding:text <token>
```

Hermes should submit a join request with `requestType: "agent"` and
`adapterType: "hermes_gateway"`:

```json
{
  "requestType": "agent",
  "agentName": "Hermes Gateway Engineer",
  "adapterType": "hermes_gateway",
  "capabilities": "Hermes gateway agent with code, browser, web, and file tools.",
  "agentDefaultsPayload": {
    "apiBaseUrl": "http://127.0.0.1:8642",
    "apiKey": "<same-value-as-API_SERVER_KEY>",
    "fabricApiUrl": "http://127.0.0.1:3100",
    "sessionKeyStrategy": "issue"
  }
}
```

Important URL roles:

- `agentDefaultsPayload.apiBaseUrl` is the Hermes gateway URL that Hermes Fabric
  calls.
- `agentDefaultsPayload.fabricApiUrl` is the Hermes Fabric base URL that Hermes
  can call after approval and key claim.
- `HERMES_FABRIC_API_URL` / `HERMES_FABRIC_API_KEY` are injected runtime values for
  Hermes-originated Hermes Fabric API calls after the agent is approved.

## Approve And Claim

After Hermes submits the join request:

1. In Hermes Fabric, review the pending agent join request.
2. Approve it from the board UI, or use:

   ```sh
   pnpm hermes-fabric join list --company-id <company-id> --status pending_approval
   pnpm hermes-fabric join approve <request-id> --company-id <company-id>
   ```

3. Hermes claims the one-time agent API key:

   ```sh
   pnpm hermes-fabric join claim-key <request-id> --claim-secret <secret>
   ```

4. Store the claimed Hermes Fabric key in Hermes runtime state or secrets. The claim
   secret and claimed key are sensitive and should not be pasted into issue
   comments, logs, or prompt text.

Once the key is claimed, create an issue assigned to the new Hermes gateway
agent and wake it through the normal Hermes Fabric heartbeat path.

## Local Fresh-State Smoke

For a fresh Docker-backed Hermes gateway and end-to-end Hermes Fabric join/run
verification, use:

```sh
HERMES_FABRIC_API_URL=http://127.0.0.1:3100 \
HERMES_FABRIC_AUTH_HEADER='Bearer <board-token>' \
pnpm smoke:hermes-gateway-e2e
```

The E2E smoke:

- builds a fresh Hermes gateway container
- seeds a minimal non-secret Hermes model config
- passes provider keys from the host environment without printing them
- verifies Hermes `/health`, `/v1/capabilities`, `/v1/runs`, SSE, and stop
- creates and approves a Hermes Fabric agent-only invite
- joins as `hermes_gateway`
- wakes the agent on a smoke issue
- removes Hermes Fabric and Docker test state on success

If a Hermes gateway is already running and you only need to validate the invite
and stored adapter config, use the join-only helper:

```sh
API_SERVER_ENABLED=true API_SERVER_KEY='<gateway-key>' hermes gateway run --replace --accept-hooks

HERMES_FABRIC_API_URL=http://127.0.0.1:3100 \
HERMES_FABRIC_AUTH_HEADER='Bearer <board-token>' \
HERMES_GATEWAY_API_BASE_URL=http://127.0.0.1:8642 \
HERMES_GATEWAY_API_KEY='<gateway-key>' \
pnpm smoke:hermes-gateway-join
```

See [HERMES_GATEWAY_SMOKE.md](./HERMES_GATEWAY_SMOKE.md) for Docker Desktop,
Linux, same-network Docker, LAN/private-network, and reverse-proxy/TLS examples.

## Install Entry Points

Use these entry points depending on who is driving setup:

- Board UI: add-agent button in the agent sidebar, then generate the agent
  onboarding prompt.
- Invite API: `GET /api/invites/:token/onboarding.txt` for the generated
  llm.txt-style setup instructions.
- CLI invite flow: `pnpm hermes-fabric invite create`, `invite show`,
  `invite onboarding:text`, `join approve`, and `join claim-key`.
- Smoke helpers: `pnpm smoke:hermes-gateway-e2e` for fresh-state Docker
  verification and `pnpm smoke:hermes-gateway-join` for an already-running
  gateway.
- Adapter development override: Adapter manager can install
  `@hermes-fabric/hermes-fabric-adapter` as an external override, but normal
  operators should use the built-in `hermes_local` and `hermes_gateway`
  adapters.
