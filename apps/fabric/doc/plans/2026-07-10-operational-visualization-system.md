# Hermes Fabric operational visualization system

Date: 2026-07-10

## Purpose

Hermes Fabric should use Casberry-style particle and 3D inspiration as an operational status language for Hermes Agency and Keryx, not as decorative motion. The visualization system must help an operator answer four questions quickly:

1. What is connected, queued, running, blocked, or failed?
2. Which relay/edge/agent path is carrying work?
3. What needs human action now?
4. Which text detail, artifact, roster row, or task thread explains the visual state?

The production system should be deterministic, bounded, accessible, and backed by Fabric state. It must not execute arbitrary generated JavaScript, allow unbounded particle counts, or hide controls behind gestures.

## MVP recommendation

MVP should be the **Keryx topology widget** on the Hermes Fabric dashboard. It is the strongest first visualization because it maps directly to Fabric's Hermes Agency direction: roster visibility, skill-fit dispatch, wake/queue semantics, A2A/P2P task status, artifacts, budgets, watchdogs, and human governance.

Agency swarm and Kanban milestone visualizations should be Phase 2. They are valuable, but both depend on the same visual grammar, legend, accessibility fallback, data-state contract, and performance controls proven by the Keryx MVP.

## Phase breakdown

### Phase 1 / MVP: Keryx topology widget

Scope:
- Dashboard card with a compact, read-only topology of the live execution substrate.
- Nodes for Fabric, VPS relay hub, Katana edge, ODS/container edge, and selected agent endpoints.
- Directed routes for trusted relay paths and active task-flow paths.
- Bounded task-flow particles/pulses that represent real task state changes.
- Text summary, legend, accessible table fallback, and click-through links to roster/task/detail surfaces.

Success criteria:
- Operator can identify in under 10 seconds: relay health, edge health, active/running flows, queued/offline targets, wake failures, blocked tasks, and next human action.
- Reduced-motion mode remains fully useful with static routes, badges, and event rows.
- Mobile default is a compact text/status summary with an explicit expand action.

### Phase 1.5: Dispatch explainability drawer

Scope:
- Side drawer shown during direct-agent or skill-fit dispatch review.
- Candidate routes ranked by skill match and availability.
- Offline agents remain valid route targets and receive visible queue badges.
- One-shot route animation after operator confirmation; text rationale remains primary.

Success criteria:
- Operator can tell why Fabric chose direct profile routing vs skill-fit routing.
- Every animated route has a matching textual route reason and status row.

### Phase 2: Agency swarm visualization

Scope:
- Department/status grouped view of agency-* profiles.
- Grouping options: department, skill family, model/provider tier, and status.
- States: online, sleeping/offline queueable, running, blocked, crashed/wake_failed, disabled/paused.
- Drill-through to Hermes Agency roster rows and dispatch history.

Success criteria:
- Operator can spot underused departments, blocked/crashed specialists, and active execution clusters without scanning a long roster.
- Visualization respects current roster semantics: offline agents are valid targets, not absent workers.

### Phase 2: Kanban milestone clusters

Scope:
- Large-workstream overview that clusters tasks by milestone/dependency group and task state.
- States: done, running/in_progress, blocked, dependency-waiting, review_required, cancelled.
- Edges show dependency/fan-in relationships, not arbitrary decorative connections.
- Drill-through to issue list filters and task detail.

Success criteria:
- Operator can see whether a milestone is blocked by dependency fan-in, review gates, or active work saturation.
- Works on large boards by aggregating first and progressively revealing details.

### Phase 3: Optional depth after validated MVP

Only after the MVP proves product value:
- Budget/watchdog heat overlays on topology/swarm views.
- Artifact provenance graph for completed work products.
- Static snapshot export for reports.
- Optional WebGL/Three.js renderer if 2D/SVG/canvas cannot meet a proven need.

## Shared visual language

### Naming

Use Hermes Agency terms in product UI:
- Fabric: operator surface / command surface.
- Keryx: relay and routing substrate.
- VPS relay hub: central relay node.
- Katana edge: operator-local edge.
- ODS/container edge: containerized execution edge.
- Agency specialist: agency-* profile endpoint.
- Task-flow particle: bounded status pulse for a real task event.

Do not use public Paperclip branding in new labels, legends, empty states, or docs for this system.

### Layout grammar

Keryx topology:
- Fabric command surface anchors top-left or left edge of the card.
- VPS relay hub is the central high-salience node.
- Katana edge and ODS/container edge sit as opposing edge nodes.
- Agent endpoints cluster near the edge that can wake/route them.
- Trust/allowlist boundaries are visible as rings or lanes, not hidden metadata.

Agency swarm:
- Departments form labeled constellations.
- Individual agents are small, selectable nodes with status rings.
- Running agents may show one bounded orbit/pulse; blocked/crashed agents use stronger static badges before motion.

Kanban milestones:
- Milestone clusters are large labeled regions.
- Task dots/cards use existing Fabric task status hues.
- Dependency edges appear only for real parent/child or blocking relationships.

### Status/state mapping

Use the existing Fabric status palette as the baseline, extending it only when needed:

| Operational state | Visual treatment | Text label | Notes |
| --- | --- | --- | --- |
| healthy/online | green ring, steady node | Online / Healthy | Do not animate just to show health. |
| sleeping/offline queueable | muted/slate ring, queue badge | Offline target / Sleeping | Must communicate still dispatchable. |
| queued | amber bead or static badge | Queued | One pulse per queue event, then static count. |
| wake_failed/crashed | amber-red ring, alert badge | Wake failed / Crashed | Persistent action state, not transient sparkle. |
| running | blue/cyan route pulse | Running | Cap simultaneous pulses. |
| blocked | red/orange held node/route | Blocked | Include reason text and action link. |
| review_required | violet badge/ring | Review required | Match in_review language. |
| completed/done | green fade or completed tick | Done | Animation is optional and short-lived. |
| dependency-waiting | amber dashed edge | Waiting on dependency | Kanban cluster only. |
| budget/watchdog risk | red heat halo | Budget/watchdog risk | Later overlay; never replaces budget text. |

Particle rules:
- Particles are event/status markers, not arbitrary ambience.
- Each visible particle must correspond to a route, task, wake, artifact, watchdog, approval, or health event.
- The renderer must apply a hard cap. Recommended initial cap: 80 particles total, 20 actively moving, with aggregation above that threshold.
- Do not rely on color or motion alone; every state appears in text, icon, shape, or table form.

## Keryx topology widget design spec

### Primary desktop card

Placement:
- Dashboard, near active agents / operational summary, above or beside activity charts depending on available width.
- 16:9 or 2:1 card, minimum useful desktop height around 280px.

Card header:
- Title: `Keryx topology`
- Subtitle: compact summary such as `Relay healthy · 3 running · 12 queued · 1 wake failed`
- Actions: `View routes`, `Open roster`, `Open tasks`; keep all controls visible as buttons or menu items.

Visual area:
- Nodes: Fabric, VPS Relay, Katana Edge, ODS Edge, Agent Clusters.
- Edges: trusted route lanes and active task-flow lanes.
- Badges: queued counts, running counts, wake_failed counts, blocked counts.
- Legend: visible by default on desktop; collapsible only with labeled button.

Interaction:
- Click/focus node: updates side summary and exposes links to roster/task filters.
- Click/focus route: shows route health, recent task events, and trust/allowlist status.
- Hover may enrich, but focus/click must provide the same information.
- No essential control should require drag, pinch, hover, or hidden gesture.

### Data contract for implementation

Frontend can implement the widget against a deterministic view model instead of raw logs:

```ts
type OperationalTopologyView = {
  generatedAt: string;
  summary: {
    relayHealth: "healthy" | "degraded" | "down" | "unknown";
    runningTasks: number;
    queuedTasks: number;
    blockedTasks: number;
    wakeFailedAgents: number;
    humanActions: number;
  };
  nodes: Array<{
    id: string;
    kind: "fabric" | "vps_relay" | "katana_edge" | "ods_edge" | "agent_cluster" | "agent";
    label: string;
    status: "healthy" | "degraded" | "offline_queueable" | "running" | "blocked" | "wake_failed" | "unknown";
    counts?: Record<string, number>;
    href?: string;
  }>;
  routes: Array<{
    id: string;
    from: string;
    to: string;
    trustState: "allowed" | "blocked" | "unknown";
    status: "idle" | "queued" | "running" | "blocked" | "wake_failed" | "completed";
    taskCount: number;
    href?: string;
  }>;
  events: Array<{
    id: string;
    routeId?: string;
    nodeId?: string;
    state: "queued" | "running" | "blocked" | "wake_failed" | "completed" | "review_required";
    label: string;
    timestamp: string;
    href?: string;
  }>;
};
```

Implementation notes:
- Derive this from existing Hermes Agency roster, dispatch records, task/run state, relay health, and activity events.
- Do not parse raw transcript text to infer operational state.
- Unknown data must render as `unknown`, not as healthy.
- Aggregate when data exceeds visual caps; show `+N more` with links to filtered list views.

## Agency swarm design spec

Purpose:
- Provide a roster-at-scale status map for large agency deployments.

Default grouping:
- Department first, then status within department.
- If department metadata is unavailable, group by skill family derived from profile skills.

Node states:
- online: green ring and `Online` label in detail panel.
- sleeping/offline: muted ring with `Offline target` / `Queueable` badge.
- running: blue activity ring and running count.
- blocked: red/orange badge and blocker count.
- crashed/wake_failed: alert badge with last error available in detail.
- disabled/paused: dimmed node with explicit `Disabled` or `Paused` label.

Required text alternative:
- A sortable roster summary table with columns: Department, Agent, Status, Current task, Queue count, Last seen, Last error/action.

MVP status:
- Phase 2, unless the dashboard roster becomes too large to operate through list/table alone before Keryx ships.

## Kanban milestone cluster design spec

Purpose:
- Provide a large-workstream map that complements, not replaces, the existing Kanban board.

Cluster model:
- Group by explicit milestone/project/parent issue where available.
- Fall back to top-level parent task clusters for nested workstreams.
- Within each cluster, aggregate done/running/blocked/dependency/review/cancelled counts.

Visual mapping:
- Done: green completed cluster fill or count ring.
- Running: blue active count ring.
- Blocked: red/orange badge with blocker count.
- Dependency-waiting: amber dashed dependency edge.
- Review-required: violet segment.

Interaction:
- Click/focus cluster opens filtered issue list or milestone detail.
- Click/focus dependency edge lists parent tasks preventing promotion.
- Large boards default to aggregation; do not render every task dot when counts exceed threshold.

MVP status:
- Phase 2. It should reuse Keryx legend, color, reduced-motion, and table-fallback patterns.

## Mobile behavior

Small screens should not load or foreground dense animated scenes by default.

### Compact default

For widths under 768px:
- Show a static status summary card first.
- Include counts for relay health, running, queued, blocked, wake_failed, and human actions.
- Show the top one to three actionable rows below the summary.
- Provide an explicit button: `Open topology map`.
- Avoid overlap with the existing mobile toolbar by keeping visualization controls inside the card or full-screen sheet, not in the global toolbar row.

### Full-screen expansion

Tap `Open topology map` to open a full-screen sheet/dialog:
- Header with title, close button, summary counts, and `Reduced motion`/`List view` control.
- Visualization canvas/SVG takes remaining space.
- Bottom or side drawer contains selected node/route details.
- All controls must be reachable with touch and keyboard.
- Touch targets: 44-48px minimum with at least 8px spacing for adjacent controls.

### Very small screens

For widths <=359px:
- Default to list/table view.
- Visualization preview may be a static thumbnail or omitted.
- Prioritize `Open topology map`, `View actions`, and `Open roster/tasks` controls.

### Reduced-motion and low-power modes

- Respect `prefers-reduced-motion: reduce` automatically.
- Add a persistent Fabric user setting to disable visualization animation.
- Pause animation when card is offscreen, document is hidden, CPU/battery saver is detected where available, or particle cap would be exceeded.
- Low-power mode uses static routes, count badges, event list, and optional short opacity changes only.

## Accessibility requirements

Required for all phases:
- Text summary with the same state information as the visual.
- Keyboard navigation for every interactive node, route, legend item, action, and expansion control.
- Visible focus ring using Fabric token colors.
- High-contrast support in dark and light modes.
- No color-only or motion-only communication.
- `prefers-reduced-motion` support and user-level animation disable.
- Screen-reader-accessible table/list fallback with links to the same destination as visual nodes.
- Canvas/WebGL/SVG region must have a concise accessible name and description.
- Dynamic state updates should use polite live-region summaries, not noisy per-particle announcements.

Recommended fallback table for Keryx MVP:
- Section: `Topology status summary`.
- Columns: Component, Status, Running, Queued, Blocked, Wake failed, Last update, Action.
- Route event list: Status, Source, Target, Task, Time, Action.

## Performance and safety requirements

Performance:
- Start with deterministic SVG or Canvas 2D. Do not make Three.js/WebGL a prerequisite for MVP.
- Hard cap visible particles and actively animated particles.
- Aggregate beyond caps and show counts.
- Pause offscreen/hidden-tab animation.
- Avoid loading heavy rendering libraries for users who only view list/table summaries.
- Target smooth interaction without competing with board, transcript, or toolbar performance.

Safety/security no-go list:
- No arbitrary generated JavaScript execution in production Fabric UI.
- No user-authored particle function bodies in the trusted app shell.
- No unbounded particle counts or unlimited event replay animation.
- No decorative particles that do not map to real Fabric/Agency/Keryx data.
- No hidden controls that only work by gesture, hover, pinch, drag, or canvas-specific trick.
- No visualization that bypasses Hermes Agency trust, allowlist, relay, queue, wake, budget, watchdog, or governance semantics.
- No public Paperclip branding in new Hermes Fabric visualization UI.
- No animation-only indication of token spend, blockers, approval requirements, or failures.

## Frontend/backend handoff

### Frontend worker should implement

- `KeryxTopologyCard` or equivalent dashboard component.
- Deterministic topology renderer with bounded particles/pulses.
- Mobile compact card and full-screen expansion.
- Reduced-motion/list mode.
- Accessible summary table and route event list.
- Legend and status tokens aligned with existing Fabric task/agent status colors.

### Backend/shared worker should implement

- A typed topology view model endpoint or composition service.
- Company-scoped access checks for topology data.
- Relay/edge/agent/task/run state mapping into the view model.
- Unknown/degraded states instead of optimistic healthy defaults.
- Tests for queueable offline agents, wake_failed agents, blocked/running tasks, relay degraded/down, and empty-state behavior.

### QA/review checklist

- Desktop card answers running/queued/blocked/wake_failed/human-action questions quickly.
- Mobile compact card does not collide with toolbar controls.
- Full-screen mobile map is closeable and keyboard/touch reachable.
- Reduced-motion mode has no continuous animation and no lost information.
- Screen reader can access equivalent status and action links.
- Particle caps and aggregation behave under high event counts.
- Unknown/degraded relay data is not rendered as healthy.
- All new labels use Hermes Fabric/Hermes Agency/Keryx naming.

## Open decisions for implementation

1. Confirm exact source of Keryx relay and edge health in the API layer.
2. Decide whether the first endpoint lives under existing Hermes Agency routes or a dashboard summary route.
3. Decide whether user animation preference is global app setting or local component preference in MVP.
4. Confirm department metadata source for agency swarm grouping before Phase 2.
