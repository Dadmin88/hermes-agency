# Security review: Casberry-style generated particle workflows for Hermes Fabric

Date: 2026-07-10
Owner: Security engineering
Scope: Proposed AI/generated particle code, third-party WebGL snippets, 3D asset import, and high-particle-count visualization workflows in Hermes Fabric.

## Verdict for MVP

Hermes Fabric MVP should ship curated static/deterministic visualizations only. Do not execute Casberry-style AI-generated JavaScript function bodies, user-authored particle behavior code, copied third-party WebGL snippets, or generated React/Three.js components in the trusted operator UI.

The safe MVP path is:

- deterministic visualization code reviewed in-repo;
- first-party Fabric/Agency state mapped to a fixed schema;
- no runtime `eval`, `new Function`, dynamic script injection, remote module import, generated component compilation, or user-authored shader/function execution;
- no arbitrary GLB/OBJ/PLY ingestion in the initial production UI;
- accessible list/table fallbacks and reduced-motion static states.

Future generated-code support should be treated as a separate high-risk feature requiring sandbox isolation, explicit security sign-off, performance budgets, and abuse tests before enablement.

## Threat model

### Assets to protect

- Operator browser session, auth cookies/tokens, company-scoped data, task comments, run logs, artifacts, work products, adapter configuration, and budget/governance controls.
- Hermes Agency trust boundaries: relay/allowlist semantics, queued task state, profile identity, and status provenance.
- Browser/device availability: CPU, GPU, memory, battery, accessibility preferences, and UI responsiveness.
- Repository and supply chain integrity for any visualization dependency or third-party snippet.

### Trust boundaries

- Trusted app shell: reviewed Fabric UI code and server APIs.
- Semi-trusted first-party data: company-scoped Fabric/Agency status, task metadata, and artifact metadata.
- Untrusted content: AI-generated JavaScript, imported particle snippets, generated React/Three.js exports, shaders, GLB/OBJ/PLY files, textures, external URLs, marketplace snippets, and comments/artifacts produced by agents or users.
- Browser graphics boundary: WebGL/GPU driver and canvas rendering, which have a history of process/GPU hangs and fingerprinting/privacy-sensitive APIs.

### Likely actors

- Malicious user or compromised agent uploading generated code/assets.
- Prompt-injected or low-quality model output producing unsafe JavaScript.
- Third-party snippet author embedding exfiltration, miners, supply-chain payloads, or denial-of-service loops.
- Accidental operator importing oversized assets or 20k+ particle scenes that degrade the board.

## Key risks

### 1. Arbitrary JS/function-body execution

Casberry-style workflows can emit function bodies for particle behavior. Running these inside Fabric would grant code access to the same origin as the operator UI unless isolated. That creates direct risk of:

- token/session exfiltration through `fetch`, image beacons, WebSocket, `navigator.sendBeacon`, or remote imports;
- data theft from DOM, IndexedDB/localStorage/sessionStorage, React state, query caches, and visible transcripts;
- unauthorized mutations through existing authenticated APIs;
- supply-chain bypass through generated code that imports remote modules or scripts;
- persistent XSS if generated code is stored as a visualization preset;
- browser/CPU/GPU DoS through infinite loops, recursive scheduling, unbounded allocations, shader compile storms, or frame loops that ignore visibility/reduced-motion state;
- clickjacking or UI spoofing if generated components render inside the trusted app shell.

Unsafe patterns for Fabric production:

- `eval`, `new Function`, dynamic `import()` of generated URLs, script tag injection, data/blob-script URLs, JSX/TSX compilation in the browser, or generated React component execution.
- User-provided GLSL/WGSL/shader strings compiled in the trusted app shell.
- Third-party snippets pasted into the app without dependency review and lockfile provenance.

### 2. Imported GLB/OBJ/PLY assets

3D asset import is not equivalent to image display. It introduces parser, decompression, GPU allocation, and privacy risks:

- oversized geometry, textures, morph targets, skeletons, animations, or embedded buffers can exhaust memory/GPU resources;
- compressed or nested assets can cause zip/decompression bombs or unexpectedly large decoded payloads;
- parser vulnerabilities in model loaders or transitive dependencies may be reachable from untrusted files;
- external texture/material references can trigger network requests and leak operator context or IP metadata;
- malicious filenames/metadata can become XSS if reflected in UI labels or logs;
- imported scenes can visually spoof UI state if rendered without clear boundaries/labels;
- asset-derived content should not be automatically indexed, summarized, or dereferenced by agent/LLM workflows, matching the existing asset/work-product metadata-only security gate.

MVP should not allow arbitrary GLB/OBJ/PLY upload/import for live dashboard rendering. If assets are allowed later, treat them as untrusted binary input with explicit MIME/extension allowlists, size caps, offline validation/conversion, stripped external references, metadata-only indexing, and human review before publication.

### 3. WebGL/GPU DoS and browser performance

20k+ particles can be legitimate for a specialized demo but dangerous for an operator control plane. Even benign code can degrade the board by:

- monopolizing the main thread or requestAnimationFrame loop;
- increasing memory churn through per-frame allocations;
- triggering GPU resets, driver instability, or tab kills on lower-end machines;
- draining laptop battery and increasing thermal load;
- making task controls, approvals, and incident response sluggish;
- ignoring `document.visibilityState`, offscreen state, background tabs, or reduced-motion preferences.

Hermes Fabric already has a safer local precedent in `ui/src/components/AsciiArtAnimation.tsx`: it caps frame rate at 24 FPS, respects `prefers-reduced-motion`, stops when the document is hidden, uses deterministic reviewed code, and renders decorative animation as `aria-hidden`. Future topology widgets should follow or exceed those constraints, while ensuring operational states also have accessible text equivalents.

### 4. Third-party dependencies and snippets

Adding Three.js/WebGL libraries, model loaders, postprocessing stacks, or copied snippets increases supply-chain and maintenance risk. Current `ui/package.json` does not include `three`, so adopting it would be a new dependency surface. Risks include:

- vulnerable transitive packages and loader-specific parser bugs;
- CDN or remote module usage that bypasses lockfile review;
- large bundle cost for users who only need list/table views;
- unclear license/provenance for AI-generated or copied code;
- stale snippets that do not follow Fabric auth, CSP, accessibility, or reduced-motion rules.

Prefer 2D/SVG/canvas with in-repo reviewed code first. If WebGL/Three.js becomes necessary, pin dependencies through the existing package manager, document why 2D is insufficient, run dependency audit/upgrade review, and lazy-load the renderer only where needed.

## Recommendations

### Safe for MVP

- Curated, read-only Keryx/Fabric topology visualization built from first-party status data.
- Deterministic mappings from `queued`, `wake_failed`, `running`, `blocked`, `completed`, `review_required`, budget, artifact, and watchdog states to fixed visual tokens.
- Static or lightly animated 2D renderer, preferably SVG/canvas before WebGL.
- Text/table fallback with identical status data, keyboard navigation, and ARIA labels.
- Reduced-motion default path that renders static graph states or event lists.
- Strict reviewed-code-only implementation: no user-authored or generated behavior code in production.

### Unsafe / not approved for MVP

- Running AI-generated particle JavaScript/function bodies in the Fabric origin.
- Pasting third-party WebGL snippets into production without review, tests, dependency provenance, and CSP impact analysis.
- Allowing operators/agents to upload generated React/Three.js components and execute them.
- Accepting arbitrary shaders, remote textures, remote model references, or generated modules.
- Rendering arbitrary GLB/OBJ/PLY files directly in the operator dashboard.
- Treating animation as the only signal for routing, budget, blocker, or incident state.

## Minimum controls for future generated-code execution

Generated-code execution should require all of the following before consideration:

1. Separate origin isolation
   - Execute untrusted visualizations on a different origin from the Fabric app, not just a component boundary.
   - Use a sandboxed iframe with no `allow-same-origin` unless a specific design proves why it is safe.
   - Prefer no `allow-scripts`; if scripts are required, combine iframe sandboxing with a dedicated origin and locked messaging protocol.

2. Capability-based API
   - Generated code must not receive tokens, cookies, raw task data, adapter configs, or unrestricted network access.
   - Parent-to-child communication must use a narrow `postMessage` schema with origin checks, versioning, and validation.
   - Data sent to the sandbox should be minimized, redacted, and immutable snapshots, not live API clients.

3. CSP and network controls
   - Fabric app CSP should forbid inline scripts and remote script sources by default.
   - Sandbox origin CSP should disallow arbitrary `connect-src`, `img-src`, `worker-src`, and `script-src` unless explicitly approved.
   - Block remote imports, external textures, tracking pixels, and data exfiltration endpoints.

4. Worker/iframe containment
   - Heavy simulation should run off the main UI thread where possible.
   - Use Web Workers or OffscreenCanvas for compute, but do not treat workers as a security boundary by themselves; they are performance isolation, not authorization.
   - Enforce lifecycle controls: start, pause, terminate, timeout, and memory/particle budget checks.

5. Static validation and review gates
   - Reject code containing dynamic code execution, remote imports, DOM access, storage access, broad network APIs, nested workers, wasm, timers without limits, or suspicious obfuscation.
   - Require human/security review before a generated visualization is promoted from prototype to reusable preset.
   - Store provenance: generator, prompt/version, dependency versions, reviewer, approval timestamp, and checksum.

6. Runtime kill switches and observability
   - Per-scene timeouts, frame-budget monitors, and user-visible stop controls.
   - Automatic pause on hidden/offscreen tabs and reduced-motion contexts.
   - Error boundaries and clear fallback UI when rendering fails.
   - Instance/admin-level feature flag to disable generated visualization execution globally.

7. Asset pipeline controls
   - Positive MIME/extension allowlist and content sniffing.
   - Hard limits on upload size, decoded geometry count, texture dimensions/count, animation count, material count, and total GPU buffer budget.
   - Offline conversion/sanitization that strips scripts, external references, unknown extensions, oversized buffers, and unsafe metadata.
   - Malware/parser scanning where feasible, and dependency updates for loaders.
   - Metadata-only LLM indexing unless a separate security gate approves content extraction.

## Performance guardrails

Initial curated visualization guardrails:

- Prefer 2D/SVG/canvas; do not add WebGL/Three.js unless a concrete interaction requires it.
- Lazy-load visualization code and keep list/table views usable without graphics bundles.
- Default target: no more than 24 FPS for decorative/status motion; lower on battery saver or reduced-power devices.
- Particle budget should be tied to viewport and device capability, not arbitrary scene exports. For MVP, keep particle-like elements in the low hundreds, not 20k+.
- Cap CPU/GPU work per frame; avoid per-frame object allocation and unbounded arrays.
- Pause animation when hidden, offscreen, minimized, or behind a collapsed panel.
- Provide a user setting and admin/operator switch to disable animations.
- Measure with low-end hardware profiles before enabling by default.
- Never allow visualization work to block approvals, task controls, transcript viewing, or incident actions.

Future WebGL-specific guardrails:

- Hard caps on draw calls, vertices, indices, textures, shader compile count, render target size, and total GPU memory estimate.
- Fail closed when caps are exceeded; show a static fallback rather than trying to render.
- No unbounded postprocessing chains or recursive render loops.
- Watchdog render health metrics: average FPS, long tasks, dropped frames, memory estimate, and automatic downgrade to static mode.

## Accessibility and reduced-motion requirements

- Every visual state must have text equivalent status and must be reachable through keyboard navigation.
- Do not rely on color alone; combine color with label, icon/shape, pattern, and text.
- Canvas/WebGL content must have an adjacent semantic table/list with the same nodes, routes, timestamps, and statuses.
- `prefers-reduced-motion: reduce` must disable motion by default and render a static graph or event list.
- Provide persistent per-user animation disablement.
- Ensure focus order, hover/focus details, and click-through targets work without a pointer device.
- Do not use flashing, rapid pulsing, or continuous motion for critical alerts; critical states need explicit textual call-to-action.
- Screen reader users must receive concise status summaries without being forced through every particle/event.

## Implementation policy statement

For Hermes Fabric, visualization is an observability aid, not an execution surface. Until a separate generated-code sandbox project is approved, all production visualization code must be reviewed source code checked into the repository and driven only by validated first-party Fabric/Agency data. Generated or third-party particle artifacts may be used as design inspiration or offline prototypes, but they must not run inside the trusted operator UI.

## Verification notes

This review was grounded in:

- `HERMES_FABRIC.md` control-plane and Agency trust-boundary direction.
- `doc/plans/2026-07-09-casberry-fabric-visualization-recommendation.md` product recommendation and no-go list.
- `doc/plans/2026-05-06-llm-wiki-paperclip-asset-security-gate.md` existing fail-closed asset/work-product policy.
- `ui/package.json`, which currently has no Three.js dependency.
- `ui/src/components/AsciiArtAnimation.tsx`, which provides a reviewed-code precedent for FPS cap, reduced-motion handling, and hidden-tab pause behavior.
