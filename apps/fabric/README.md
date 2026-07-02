<p align="center">
  <a href="#quickstart"><strong>Quickstart</strong></a> &middot;
  <a href="./HERMES_FABRIC.md"><strong>Foundation</strong></a> &middot;
  <a href="./doc/plans/2026-06-29-hermes-fabric-rebrand-map.md"><strong>Rebrand Map</strong></a>
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License" /></a>
</p>

<br/>

# Hermes Fabric is the frontend for Hermes Agency.

Hermes Fabric is a Paperclip-derived MIT frontend for Hermes Agency. The main product is **Hermes Agency**: the multi-agent workforce, agency-* roster, skill-fit routing, wake/queue behavior, A2A/P2P transport, and trust boundary. Hermes Fabric is the persistent visual surface for that workforce.

See [`HERMES_FABRIC.md`](./HERMES_FABRIC.md) for the fork direction, product relationship, and first milestones.

Open-source orchestration for Hermes Agency teams.

**Hermes Agency is the workforce. Hermes Fabric is the interface.**

Hermes Fabric starts from Paperclip's Node.js server and React UI foundation, then builds toward roster visibility, skill-fit dispatch, task threads, artifacts, status, budgets, watchdogs, and human governance for Hermes Agency.

It looks like a task manager. Under the hood: agency rosters, wake queues, task dispatch, artifacts, budgets, governance, liveness, and Hermes Agency coordination.

**Manage Hermes Agency work, not generic agent sprawl.**

|        | Step            | Example                                                            |
| ------ | --------------- | ------------------------------------------------------------------ |
| **01** | Define the task | _"Review this Hermes Agency routing change for security risks."_   |
| **02** | Select by skill | Code reviewer, backend engineer, accessibility reviewer, etc.      |
| **03** | Dispatch/watch  | Wake or queue the specialist, monitor status, capture artifacts.   |

<br/>

<div align="center">
<table>
  <tr>
    <td align="center"><strong>Works<br/>with</strong></td>
    <td align="center"><img src="doc/assets/logos/openclaw.svg" width="32" alt="OpenClaw" /><br/><sub>OpenClaw</sub></td>
    <td align="center"><img src="doc/assets/logos/claude.svg" width="32" alt="Claude" /><br/><sub>Claude Code</sub></td>
    <td align="center"><img src="doc/assets/logos/codex.svg" width="32" alt="Codex" /><br/><sub>Codex</sub></td>
    <td align="center"><img src="doc/assets/logos/cursor.svg" width="32" alt="Cursor" /><br/><sub>Cursor</sub></td>
    <td align="center"><img src="doc/assets/logos/bash.svg" width="32" alt="Bash" /><br/><sub>Bash</sub></td>
    <td align="center"><img src="doc/assets/logos/http.svg" width="32" alt="HTTP" /><br/><sub>HTTP</sub></td>
  </tr>
</table>

<em>If it can receive a heartbeat, it's hired.</em>

</div>

<br/>

## Hermes Fabric is right for you if

- ✅ You want a frontend for the **Hermes Agency** workforce
- ✅ You coordinate many `agency-*` specialists by skill fit
- ✅ You want offline agents to remain valid targets through wake/queue behavior
- ✅ You want persistent task threads, artifacts, logs, budgets, and watchdogs around agency work
- ✅ You want to monitor Hermes Agency from a real dashboard instead of only CLI/tool output
- ✅ You want Hermes Agency to remain the main product while Hermes Fabric becomes its interface

<br/>

## Features
<table>
<tr>
<td align="center" width="33%">
<h3>🔌 Hermes Agency Native</h3>
Built around the `agency-*` workforce, skill-fit routing, wake queues, and task artifacts.
</td>
<td align="center" width="33%">
<h3>🎯 Task Context</h3>
Every task carries the objective, routing context, project context, and expected artifact shape.
</td>
<td align="center" width="33%">
<h3>💓 Wake / Queue Lifecycle</h3>
Offline specialists remain valid targets. Wake attempts, queue state, and failures become visible.
</td>
</tr>
<tr>
<td align="center">
<h3>💰 Cost Control</h3>
Budgets and guardrails around agency tasks. No runaway loops without operator visibility.
</td>
<td align="center">
<h3>🧵 Task Threads</h3>
Persistent work threads for dispatch, status, logs, decisions, returned artifacts, and validation evidence.
</td>
<td align="center">
<h3>🎫 Audit Trail</h3>
Every assignment, wake attempt, status transition, comment, artifact, and decision is traceable.
</td>
</tr>
<tr>
<td align="center">
<h3>🛡️ Governance</h3>
Approve, pause, resume, reroute, or block agency tasks from the operator surface.
</td>
<td align="center">
<h3>📊 Roster Visibility</h3>
Show all specialists, skills, descriptions, online/offline state, wake attempts, and last errors.
</td>
<td align="center">
<h3>📱 Mobile Ready</h3>
Monitor and route Hermes Agency work from anywhere.
</td>
</tr>
</table>

<br/>

## Problems Hermes Fabric solves

| Without Hermes Fabric                                                                                                                 | With Hermes Fabric                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| ❌ You have 20 Claude Code tabs open and can't track which one does what. On reboot you lose everything.                              | ✅ Tasks are ticket-based, conversations are threaded, sessions persist across reboots.                                                |
| ❌ You manually gather context from several places to remind your bot what you're actually doing.                                     | ✅ Context flows from the task through the project objective — your specialist sees what to do and why.                               |
| ❌ Folders of agent configs are disorganized and you're re-inventing task management, communication, and coordination between agents. | ✅ Hermes Fabric gives you task threads, specialist visibility, delegation, and governance around Hermes Agency. |
| ❌ Runaway loops waste hundreds of dollars of tokens and max your quota before you even know what happened.                           | ✅ Cost tracking surfaces token budgets and throttles agents when they're out. Management prioritizes with budgets.                    |
| ❌ You have recurring jobs (customer support, social, reports) and have to remember to manually kick them off.                        | ✅ Heartbeats handle regular work on a schedule. Management supervises.                                                                |
| ❌ You have work to route, but need to manually decide which agency profile should handle it.                                          | ✅ Add a task in Hermes Fabric. Skill-fit routing points it at the right Hermes Agency specialist.                                    |

<br/>

## Why Hermes Fabric is special

Hermes Fabric keeps the useful orchestration patterns while making Hermes Agency the source of truth for execution.

|                                   |                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Atomic execution.**             | Task checkout and budget enforcement are atomic, so no double-work and no runaway spend.                      |
| **Persistent agent state.**       | Agents resume the same task context across heartbeats instead of restarting from scratch.                     |
| **Runtime skill context.**        | Agency specialists can receive the task, routing context, and project context they need without retraining.   |
| **Governance with rollback.**     | Approval gates are enforced, config changes are revisioned, and bad changes can be rolled back safely.        |
| **Goal-aware execution.**         | Tasks carry full goal ancestry so agents consistently see the "why," not just a title.                        |
| **Portable team templates.**      | Export/import teams, agents, and skills with secret scrubbing and collision handling.                         |
| **True workspace isolation.**     | Every entity is workspace-scoped, so one deployment can run many agency teams with separate data and audit trails. |

<br/>

## What's Under the Hood

Hermes Fabric is a real frontend foundation, not a thin wrapper. Before building all of this from scratch, start from the proven chassis already here:

```
┌──────────────────────────────────────────────────────────────┐
│                       HERMES FABRIC SERVER                   │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│  │Identity & │  │  Work &   │  │ Heartbeat │  │Governance │  │
│  │  Access   │  │   Tasks   │  │ Execution │  │& Approvals│  │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘  │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│  │ Org Chart │  │Workspaces │  │  Plugins  │  │  Budget   │  │
│  │ & Agents  │  │ & Runtime │  │           │  │ & Costs   │  │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘  │
│                                                              │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  │
│  │ Routines  │  │ Secrets & │  │ Activity  │  │ Workspace │  │
│  │& Schedules│  │  Storage  │  │ & Events  │  │Portability│  │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘  │
└──────────────────────────────────────────────────────────────┘
         ▲              ▲              ▲              ▲
   ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐
   │  Claude   │  │   Codex   │  │   CLI     │  │ HTTP/web  │
   │   Code    │  │           │  │  agents   │  │   bots    │
   └───────────┘  └───────────┘  └───────────┘  └───────────┘
```

### The Systems

<table>
<tr>
<td width="50%">

**Identity & Access** — Two deployment modes (trusted local or authenticated), board users, agent API keys, short-lived run JWTs, workspace memberships, invite flows, and agent onboarding. Every mutating request is traced to an actor.

</td>
<td width="50%">

**Agency Roster & Specialists** — Specialists have roles, skills, descriptions, permissions, and budgets. Hermes Fabric should surface the Hermes Agency roster, including offline agents that can be woken or queued for later execution.

</td>
</tr>
<tr>
<td>

**Work & Task System** — Tasks carry workspace/project/objective/parent links, atomic checkout with execution locks, first-class blocker dependencies, comments, documents, attachments, work products, labels, and inbox state. No double-work, no lost context.

</td>
<td>

**Heartbeat Execution** — DB-backed wakeup queue with coalescing, budget checks, workspace resolution, secret injection, skill loading, and adapter invocation. Runs produce structured logs, cost events, session state, and audit trails. Recovery handles orphaned runs automatically.

</td>
</tr>
<tr>
<td>

**Workspaces & Runtime** — Project workspaces, isolated execution workspaces (git worktrees, operator branches), and runtime services (dev servers, preview URLs). Agents work in the right directory with the right context every time.

</td>
<td>

**Governance & Approvals** — Board approval workflows, execution policies with review/approval stages, decision tracking, budget hard-stops, agent pause/resume/terminate, and full audit logging. Nothing ships without your sign-off.

</td>
</tr>
<tr>
<td>

**Budget & Cost Control** — Token and cost tracking by workspace, specialist, project, objective, task, provider, and model. Scoped budget policies with warning thresholds and hard stops. Overspend pauses agents and cancels queued work automatically.

</td>
<td>

**Routines & Schedules** — Recurring tasks with cron, webhook, and API triggers. Concurrency and catch-up policies. Each routine execution creates a tracked issue and wakes the assigned agent — no manual kick-offs needed.

</td>
</tr>
<tr>
<td>

**Plugins** — Instance-wide plugin system with out-of-process workers, capability-gated host services, job scheduling, tool exposure, and UI contributions. Extend Hermes Fabric without forking it again.

</td>
<td>

**Secrets & Storage** — Instance and workspace secrets, encrypted local storage, provider-backed object storage, attachments, and work products. Sensitive values stay out of prompts unless a scoped run explicitly needs them.

</td>
</tr>
<tr>
<td>

**Activity & Events** — Mutating actions, heartbeat state changes, cost events, approvals, comments, and work products are recorded as durable activity so operators can audit what happened and why.

</td>
<td>

**Workspace Portability** — Export and import agency workspaces — specialists, skills, projects, routines, and tasks — with secret scrubbing and collision handling. One deployment, many workspaces, complete data isolation.

</td>
</tr>
</table>

<br/>

## What Hermes Fabric is not

|                              |                                                                                                                      |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| **Not a chatbot.**           | Agents have jobs, not chat windows.                                                                                  |
| **Not an agent framework.**  | Hermes Agency owns the workforce substrate. Hermes Fabric is the frontend for operating it.                          |
| **Not a workflow builder.**  | No drag-and-drop pipeline claim. Hermes Fabric models routed agency work, status, artifacts, and governance.         |
| **Not a prompt manager.**    | Specialists bring their own prompts, skills, models, and runtimes through Hermes Agency.                             |
| **Not a single-agent tool.** | This is for teams of specialists. If you have twenty agency profiles, Hermes Fabric should make them visible.        |
| **Not a code review tool.**  | Hermes Fabric routes and tracks work. Bring or build the review process through Hermes Agency specialists.           |

<br/>

## Quickstart

Open source. Self-hosted. Source checkouts now expose a `hermes-fabric` CLI alias while keeping the upstream `paperclipai` command for compatibility.

```bash
pnpm hermes-fabric onboard --yes
```

> **Troubleshooting: private npm registry `.npmrc`**
>
> If the compatibility fallback below fails with an `E404` for `paperclipai` (or similar) and you use a private npm registry (for example GitHub Packages) via a global `~/.npmrc`, `npx` may be resolving `paperclipai` against that private registry instead of the public npm registry.
>
> Diagnostic:
>
> ```bash
> npm config get registry
> ```
>
> Workaround (cross-platform; force the public npm registry for this command):
>
> ```bash
> npx --registry https://registry.npmjs.org paperclipai onboard --yes
> ```

That quickstart path now defaults to trusted local loopback mode for the fastest first run. To start in authenticated/private mode instead, choose a bind preset explicitly:

```bash
pnpm hermes-fabric onboard --yes --bind lan
# or:
pnpm hermes-fabric onboard --yes --bind tailnet
```

If you already have the upstream app configured, rerunning `onboard` keeps the existing config in place. Use `hermes-fabric configure`; `paperclipai configure` remains as a compatibility alias during the rename window.

Or manually:

```bash
git clone https://github.com/paperclipai/paperclip.git Hermes_Fabric
cd Hermes_Fabric
pnpm install
pnpm hermes-fabric onboard --yes
pnpm dev
```

This starts the API server at `http://localhost:3100`. An embedded PostgreSQL database is created automatically — no setup required.

Hermes Kanban task projection is disabled unless explicitly configured. To enable it, set both `FABRIC_HERMES_KANBAN_DB` and `FABRIC_HERMES_KANBAN_COMPANY_ID` (or the legacy `PAPERCLIP_` aliases) so Fabric knows which local Kanban database to read and which single company should receive projected tasks. Without that explicit opt-in and scope, Fabric leaves Hermes tasks unprojected and returns `X-Hermes-Kanban-Sync: unavailable` plus `X-Hermes-Kanban-Sync-Message`. Projected issue descriptions include only task IDs, status, priority, assignee, and block kind by default; set `FABRIC_HERMES_KANBAN_INCLUDE_DETAILS=true` only if the operator intentionally wants task bodies, workspace paths, tenant labels, run summaries/errors, block reasons, and task results copied into Fabric issues.

> **Requirements:** Node.js 20+, pnpm 9.15+

<br/>

## FAQ

**What does a typical setup look like?**
Locally, a single Node.js process manages an embedded Postgres and local file storage. For production, point it at your own Postgres and deploy however you like. Configure projects, agents, and goals — the agents take care of the rest.

For local operator use, Tailscale can expose the dashboard privately while keeping the deployment self-hosted.

**Can I run multiple workspaces?**
Yes. A single deployment can run multiple workspaces with data isolation.

**How is Hermes Fabric different from Hermes Agency?**
Hermes Agency is the main product and execution substrate. Hermes Fabric is the frontend for routing, observing, and governing Hermes Agency work.

**Why not just use a generic task tracker?**
Hermes Agency work needs specialist routing, wake/queue semantics, artifacts, execution state, budget guardrails, and operator governance in one place.

(Bring-your-own-ticket-system is on the Roadmap)

**Do agents run continuously?**
By default, agents can run on scheduled heartbeats and event-based triggers. Hermes Fabric should make those lifecycle events visible around Hermes Agency tasks.

<br/>

## Development

```bash
pnpm dev              # Full dev (API + UI, watch mode)
pnpm dev:once         # Full dev without file watching
pnpm dev:server       # Server only
pnpm build            # Build all
pnpm typecheck        # Type checking
pnpm test             # Cheap default test run (Vitest only)
pnpm test:watch       # Vitest watch mode
pnpm test:e2e         # Playwright browser suite
pnpm db:generate      # Generate DB migration
pnpm db:migrate       # Apply migrations
```

`pnpm test` does not run Playwright. Browser suites stay separate and are typically run only when working on those flows or in CI.

See [doc/DEVELOPING.md](doc/DEVELOPING.md) for the full development guide.

<br/>

## Roadmap

- ✅ Safe local fork and upstream attribution
- ✅ Foundation docs and rebrand map
- ✅ Initial public README rebrand
- ✅ Initial runtime branding pass
- ✅ Hermes Agency roster API
- ✅ Hermes Agency roster UI
- ✅ Task packet preview from existing tasks
- ✅ Hermes Agency dispatch bridge
- ⚪ Artifact/status sync into task threads
- ⚪ CLI/package/config rename pass
- ⚪ New Hermes Fabric assets and screenshots

This is the Hermes Fabric roadmap preview. See the detailed checklist in [doc/plans/2026-06-29-hermes-fabric-checklist.md](doc/plans/2026-06-29-hermes-fabric-checklist.md).

<br/>

## Plugins

Hermes Fabric inherits the upstream plugin architecture. A Hermes Agency-specific plugin and adapter pass will come after the initial rebrand and roster surface.

## Observability

Hermes Fabric inherits opt-in OpenTelemetry auto-instrumentation for the server (traces only). It activates when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and supports `grpc`, `http/protobuf`, and `http/json` via the standard `OTEL_EXPORTER_OTLP_PROTOCOL` env var. The `@opentelemetry/*` packages are optional peer dependencies — install them only if you want tracing. See [doc/observability.md](doc/observability.md) for install commands and the full env-var reference.

## Telemetry

Hermes Fabric currently inherits upstream anonymous usage telemetry behavior. No personal information, issue content, prompts, file paths, or secrets are collected. Private repository references are hashed with a per-install salt before being sent.

Telemetry is **enabled by default** and can be disabled with any of the following:

| Method               | How                                                     |
| -------------------- | ------------------------------------------------------- |
| Environment variable | `PAPERCLIP_TELEMETRY_DISABLED=1`                        |
| Standard convention  | `DO_NOT_TRACK=1`                                        |
| CI environments      | Automatically disabled when `CI=true`                   |
| Config file          | Set `telemetry.enabled: false` in the local app config |

## Contributing

We welcome contributions. See the [contributing guide](CONTRIBUTING.md) for details.

<br/>

## License

Hermes Fabric is a renamed fork of `paperclipai/paperclip`, which is MIT licensed. Preserve the upstream MIT license attribution in `LICENSE`.

<br/>

---

<p align="center">
  <sub>Open source under MIT. Built for people who want to get work done, not babysit agents.</sub>
</p>
