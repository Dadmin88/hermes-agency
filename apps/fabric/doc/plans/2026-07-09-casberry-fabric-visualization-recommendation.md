# Casberry-style particle/3D visualization recommendation for Hermes Fabric

Date: 2026-07-09

## Source context

- Reference site: `https://particles.casberry.in/` / Particles by Casberry.
- Live access note: browser and `curl -I` reached the site but were stopped by Cloudflare security verification (`HTTP 403`, `cf-mitigated: challenge`, page title `Just a moment...`). This recommendation therefore relies on the task-provided Casberry source context rather than live visual inspection.
- Casberry capability context from the task brief: WebGL/Three.js particle simulations; text, image, and 3D imports; AI-prompted particle function bodies; exports to Vanilla JS, React, Three.js, wallpapers, PLY, GLB, and OBJ.
- Hermes Fabric context: Fabric is the persistent operator surface for Hermes Agency/Keryx execution: roster visibility, skill-fit routing, wake/queue state, A2A/P2P task status, artifacts, budgets, watchdogs, and human governance.

## Recommendation

Adopt the Casberry inspiration as a curated operational visualization pattern, not as an end-user particle-code generator. The MVP should be a Keryx topology widget that makes live Agency routing state easier to understand: VPS relay hub, Katana edge, ODS edge, queued/running/completed/blocked task-flow particles, and trust/allowlist boundaries. Treat particles as a compact status language for operators, not decoration.

## Highest-value integrations

1. Keryx topology map: show the VPS relay as the center node, Katana and ODS as edge nodes, and Agency specialists as clustered endpoints. Particle motion should encode task traffic: queued pulses, active streams, failed wake ripples, blocked red/orange holds, completed green fades.

2. Skill-fit dispatch preview: before a task is sent, animate candidate agents by skill match and availability. The operator should see why routing chose a direct profile or skill-fit route, including offline-but-queueable specialists. This directly supports Fabric's product promise: routing decisions are inspectable.

3. Task thread activity strip: add a lightweight particle timeline inside issue/task detail pages. It should map comments, A2A state changes, artifacts, budget events, watchdog interventions, and approval gates onto one readable flow so raw transcripts stay behind progressive disclosure.

4. Budget/watchdog heat layer: overlay spend velocity, turn limits, stale heartbeats, and reviewer handoffs onto the topology. This is useful because hidden token burn and stuck agents are core operator fears; visualization should make risk visible before failure.

5. Artifact provenance graph: for completed tasks, show how reports, screenshots, diffs, logs, and validation evidence moved from agent to work product. This ties the visual system to Fabric's output-first model rather than generic animation.

## UX sketches in prose

- Dashboard topology card: a compact 16:9 panel at the top of the Agency dashboard. The relay hub sits center-left; Katana and ODS edges sit right/left; agents orbit in skill clusters. A legend maps particle colors and motion to `queued`, `wake_failed`, `running`, `blocked`, `completed`, and `review_required`. Clicking a node filters the roster and task list.

- Dispatch explainability drawer: when the operator assigns a task, a side drawer shows candidate routes. Matched agents glow by skill confidence, offline agents get a queue badge, and the chosen path animates once from Fabric to Keryx to the target agent. The drawer includes text reasons; the animation is supporting evidence, never the only explanation.

- Task detail micro-flow: under the task title, a thin particle rail marks events in order: dispatch, wake, run start, artifact upload, watchdog, reviewer, complete/block. Hover/focus shows exact timestamps and status messages. This gives a fast status scan without forcing the user into raw logs.

- Incident/risk mode: when a run exceeds budget velocity or heartbeat expectations, the topology dims normal traffic and emphasizes the risky edge or agent cluster. The call to action is concrete: pause, reassign, inspect transcript, or approve budget extension.

## Accessibility, mobile, and performance constraints

- Accessibility: every visual state must have text and ARIA-equivalent status. Do not rely on color, motion, or canvas-only content. Keyboard focus must reach nodes, routes, legend items, and related task links. Provide a table/list fallback with the same data.

- Reduced motion: respect `prefers-reduced-motion` by defaulting to static graph states, subtle opacity changes, or a non-animated event list. Offer a persistent user setting to disable animation.

- Mobile: default to the task/event list and simplified topology. Avoid dense 3D scenes on small screens; use drill-down cards for relay, edge, agent, task, and artifact details.

- Performance: cap particles and frame rate, pause animation when offscreen or tab-hidden, avoid loading Three.js for users who only need list views, and use a 2D/SVG/canvas implementation first unless a real 3D need is proven. The widget must not compete with transcripts, logs, or board interactions.

- Security: never execute arbitrary generated JavaScript in the production UI. If Casberry-style AI prompt workflows are explored, outputs must become reviewed, static, sandboxed assets or design prototypes outside the trusted app shell.

## Prototype first

Prototype the dashboard topology card as a read-only, curated Keryx topology visualization using existing Fabric/Agency state fixtures:

- Nodes: VPS relay hub, Katana edge, ODS edge, agent clusters, selected specialist nodes.
- Edges: allowed/trusted routing paths and task-flow paths.
- States: queued, wake_failed, running, blocked, completed, review_required.
- Fallback: equivalent accessible status table and reduced-motion static mode.
- Success test: an operator can answer in under 10 seconds: what is running, what is queued/offline, where routing failed, what needs human action, and which artifacts were produced.

Use a simple deterministic renderer first. Only evaluate Three.js/WebGL after the product language and data mapping are validated.

## MVP/backlog

Must have for MVP:

- Curated Keryx topology widget on the dashboard.
- Deterministic mapping from real Fabric/Agency statuses to visual states.
- Reduced-motion and mobile/list fallback.
- Click-through from nodes/routes to roster, tasks, artifacts, and logs.
- Security/performance review before production enablement.

Should have next:

- Dispatch explainability drawer with skill-fit route preview.
- Budget/watchdog heat overlays.
- Task-detail micro-flow rail.

Could have later:

- Artifact provenance graph.
- Operator-selectable visual themes.
- Export of static topology snapshots for status reports.

Won't have / explicit no-go list:

- No arbitrary generated JS execution in the production UI.
- No user-authored particle function bodies running inside Fabric.
- No decorative particles that do not explain a real Agency/Keryx workflow.
- No 3D-first implementation before 2D/read-only value is proven.
- No motion-only or color-only status communication.
- No visualization that bypasses Hermes Agency trust, allowlist, relay, queue, or governance semantics.
- No hidden token/spend activity represented only as animation without textual budget data.
