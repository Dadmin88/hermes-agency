---
name: create-issue-interaction-ui
description: Developer/maintainer skill for extending typed issue-thread interaction cards in Hermes Fabric.
---

# Create an issue interaction UI

This is a Developer/maintainer skill for contributors changing the Fabric source tree. Do NOT install this on production Paperclip agents. It describes repository internals and is intentionally excluded from the runtime skill bundle under `skills/`.

## Use this skill when

Use this guide when a new typed interaction must be represented in an issue thread from storage through API serialization and UI rendering. Do not use it for ordinary comments, activity entries, or untyped generated HTML.

## Required contract path

1. Define or extend the interaction kind and shared payload contract in `packages/shared/src/constants.ts` and the associated shared types and validators.
2. Implement server-side creation, validation, and serialization in `server/src/services/issue-thread-interactions.ts`.
3. Render the typed payload in `ui/src/components/IssueThreadInteractionCard.tsx` using existing design-system components.
4. Add plugin SDK fixtures and helpers in `packages/plugins/sdk/src/testing.ts` when plugins can produce the interaction.
5. Update route or API-client contracts if the interaction changes the wire shape.

## Safety requirements

- Treat interaction payloads as untrusted data.
- Do not execute scripts or render arbitrary HTML from a payload.
- Validate discriminated-union fields at the server boundary.
- Enforce company and issue access before reading or writing interactions.
- Keep mutations auditable and idempotent where a retry can occur.
- Provide keyboard access, reduced-motion behavior, and readable fallback text.
- Never place credentials, private URLs, local paths, or raw provider responses in the payload.

## Implementation sequence

1. Find the closest existing interaction kind and follow its end-to-end data flow.
2. Add the smallest shared type and validator change needed for the new kind.
3. Add service tests for valid input, malformed input, unauthorized access, and serialization.
4. Add the UI card with explicit empty, loading, error, and unsupported-version states.
5. Add component tests for the main action, keyboard operation, and fallback rendering.
6. Add SDK test helpers only after the shared and server contracts are stable.
7. Verify older clients render a safe fallback instead of failing the entire thread.

## Verification

Run the smallest focused tests first, then the repository handoff gates:

```sh
pnpm --filter @paperclipai/server test -- issue-thread-interactions
pnpm --filter @paperclipai/ui test -- IssueThreadInteractionCard
pnpm -r typecheck
pnpm test:run
pnpm build
```

Do not skip or delete an existing regression test to make a new interaction pass. If the interaction requires a schema change, follow the database workflow in `AGENTS.md` and include the generated migration.
