# Agent Pool Manager — Sleep/Wake Architecture

## Vision
All 50+ agency profiles are discoverable and available, but only a few run as active A2A nodes at any time. Agents wake on demand, work, and go back to sleep. Resource-efficient, scalable, autonomous.

## Current State
- Each A2A node is a persistent daemon process
- Running 50+ daemons = 50+ processes = too many resources
- Only Hermes (VPS) + local workstation are active right now
- 50+ agency profiles are configured but not running

## Architecture

```
┌─────────────────────────────────────────────┐
│              Agent Registry                  │
│         (always running, lightweight)        │
│  ┌─────────────────────────────────────────┐ │
│  │ 50+ agent definitions:                  │ │
│  │ - SOUL.md, ROUTING.md                   │ │
│  │ - skills, capabilities                  │ │
│  │ - model assignment                      │ │
│  │ - status: sleeping / waking / active    │ │
│  │ - last_active timestamp                 │ │
│  │ - peer_id (when active)                 │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
                      ↕
┌─────────────────────────────────────────────┐
│            Orchestrator Node                 │
│          (always running, routes)            │
│  - Receives tasks                           │
│  - Queries registry for best agent          │
│  - Wakes the agent if sleeping              │
│  - Delegates task via A2A                   │
│  - Tracks completion                        │
│  - Puts agent back to sleep after idle      │
└─────────────────────────────────────────────┘
                      ↕
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Agent A  │ │ Agent B  │ │ Agent C  │
│ (active) │ │ (sleep)  │ │ (sleep)  │
│ node on  │ │ node off │ │ node off │
└──────────┘ └──────────┘ └──────────┘
```

---

## Phase 1: Agent Registry

**Goal:** A lightweight registry that knows about all 50+ agents, even when they're sleeping.

### 1.1 Registry Data Model

- [ ] Create `registry.json` at `~/.hermes/agency/registry.json`
- [ ] Schema per agent:
  ```json
  {
    "agents": {
      "agency-orchestrator": {
        "status": "sleeping",
        "skills": ["task-routing", "decomposition", "coordination"],
        "model": "gpt-5.5",
        "provider": "openai",
        "peer_id": null,
        "last_active": null,
        "last_task": null,
        "idle_timeout_minutes": 5,
        "profile_path": "~/.hermes/profiles/agency-orchestrator"
      }
    }
  }
  ```
- [ ] Auto-populate from profile definitions in the repo
- [ ] Update when agents wake/sleep
- [ ] Query by skill, status, or name

### 1.2 Registry API

- [ ] Simple REST API or CLI interface:
  - `registry list` — show all agents with status
  - `registry find <skill>` — find agents with matching skill
  - `registry status <agent>` — get agent status
  - `registry wake <agent>` — wake an agent
  - `registry sleep <agent>` — put agent to sleep
- [ ] API runs on a lightweight HTTP server (Python, same VPS)
- [ ] Or: just a CLI tool that reads/writes registry.json

### 1.3 Auto-Discovery from Repo

- [ ] Script scans `~/Hermes_Agency/hermes-agency/default_staff/profiles/`
- [ ] For each profile, extracts skills from SOUL.md/ROUTING.md
- [ ] Registers in registry.json
- [ ] Runs on startup and periodically (every hour)

### 1.4 Validation

- [ ] Registry lists all 50+ agents
- [ ] `registry find "frontend"` returns frontend-engineer
- [ ] `registry find "design"` returns art-director, brand-designer, etc.
- [ ] Registry persists across restarts

**Deliverable:** A lightweight registry that knows about all agents, always online.

---

## Phase 2: Sleep/Wake Lifecycle

**Goal:** Agents can be started and stopped on demand. Only active agents consume resources.

### 2.1 Wake Mechanism

- [ ] `wake_agent(agent_name)` function:
  - Reads agent config from registry
  - Starts A2A node: `hermes -p <agent> agency start`
  - Waits for node to register with relay
  - Updates registry: status → "active", peer_id → <id>
  - Returns peer_id
- [ ] Wake timeout: if node doesn't start in 30 seconds, mark as "failed"
- [ ] Wake is idempotent: if already active, return existing peer_id

### 2.2 Sleep Mechanism

- [ ] `sleep_agent(agent_name)` function:
  - Stops A2A node: `hermes -p <agent> agency stop`
  - Updates registry: status → "sleeping", peer_id → null
  - Preserves profile state (SOUL.md, config, etc.)
- [ ] Auto-sleep: after `idle_timeout_minutes` with no tasks, agent goes to sleep
- [ ] Sleep is idempotent: if already sleeping, no-op

### 2.3 Idle Detection

- [ ] Track last task timestamp per agent
- [ ] Background thread checks every 60 seconds
- [ ] If `now - last_active > idle_timeout_minutes` → sleep
- [ ] Configurable timeout per agent (default: 5 minutes)

### 2.4 Resource Limits

- [ ] Config: `agency.pool.max_active_agents: 10` (default)
- [ ] If at limit, put oldest idle agent to sleep before waking new one
- [ ] Orchestrator is always active (never put to sleep)

### 2.5 Validation

- [ ] `wake_agent("agency-frontend-engineer")` starts the node
- [ ] `sleep_agent("agency-frontend-engineer")` stops the node
- [ ] Auto-sleep works after idle timeout
- [ ] Resource limit enforced (max 10 active)
- [ ] Orchestrator stays active

**Deliverable:** Agents can be started/stopped on demand. Only active agents consume resources.

---

## Phase 3: Orchestrator Integration

**Goal:** The orchestrator automatically wakes agents when needed and puts them to sleep when done.

### 3.1 Task Routing with Wake

- [ ] Orchestrator receives a task
- [ ] Queries registry for agents with matching skills
- [ ] If best agent is sleeping → wake it
- [ ] Wait for agent to become active
- [ ] Delegate task via A2A
- [ ] Track completion
- [ ] After completion, start idle timer

### 3.2 Wake-on-Demand Flow

```
Orchestrator: "I need a frontend engineer"
    ↓
Registry: "agency-frontend-engineer is sleeping"
    ↓
Orchestrator: wake_agent("agency-frontend-engineer")
    ↓
Registry: status → "waking"
    ↓
Node starts, registers with relay
    ↓
Registry: status → "active", peer_id → "12D3KooW..."
    ↓
Orchestrator: a2a_send(peer_id, task)
    ↓
Agent works, completes task
    ↓
Orchestrator: starts idle timer
    ↓
After 5 min idle: sleep_agent("agency-frontend-engineer")
```

### 3.3 Parallel Wake

- [ ] When a task needs multiple agents, wake them in parallel
- [ ] Example: landing page needs frontend + copywriter + art-director
- [ ] Wake all 3 simultaneously, delegate tasks, track all

### 3.4 Wake Failure Handling

- [ ] If an agent fails to wake (timeout, error):
  - Log the error
  - Try the next best agent with matching skills
  - If no alternatives, escalate to an operator
- [ ] Retry logic: max 3 attempts per agent

### 3.5 Validation

- [ ] Orchestrator wakes agent on demand
- [ ] Multiple agents woken in parallel
- [ ] Idle agents go to sleep automatically
- [ ] Wake failures handled gracefully

**Deliverable:** Orchestrator automatically manages agent lifecycle.

---

## Phase 4: Pool Manager Service

**Goal:** A background service that manages the agent pool, handles wake/sleep, and monitors health.

### 4.1 Pool Manager Daemon

- [ ] Lightweight Python service running on VPS
- [ ] Manages the registry
- [ ] Handles wake/sleep requests
- [ ] Monitors agent health
- [ ] Enforces resource limits
- [ ] Runs as systemd service: `hermes-agency-pool.service`

### 4.2 Pool Manager API

- [ ] REST API endpoints:
  - `GET /pool/agents` — list all agents with status
  - `GET /pool/agents/<name>` — get agent details
  - `POST /pool/agents/<name>/wake` — wake an agent
  - `POST /pool/agents/<name>/sleep` — put agent to sleep
  - `GET /pool/status` — pool health (active count, sleeping count, etc.)
- [ ] Also accessible via CLI: `hermes agency pool status`

### 4.3 Health Monitoring

- [ ] Check active agents every 60 seconds
- [ ] If an agent's node crashed → mark as "failed", attempt restart
- [ ] If restart fails → mark as "unavailable", alert an operator
- [ ] Track uptime per agent

### 4.4 Scaling Policy

- [ ] Config: `agency.pool.min_active: 1` (orchestrator always on)
- [ ] Config: `agency.pool.max_active: 10`
- [ ] Config: `agency.pool.idle_timeout_minutes: 5`
- [ ] Config: `agency.pool.wake_timeout_seconds: 30`
- [ ] Pool manager enforces these limits

### 4.5 Validation

- [ ] Pool manager service runs persistently
- [ ] REST API responds correctly
- [ ] Health monitoring detects crashed agents
- [ ] Scaling policy enforced

**Deliverable:** Production-grade agent pool management.

---

## Phase 5: Advanced Features

**Goal:** Smart scheduling, pre-warming, and predictive wake.

### 5.1 Pre-Warming

- [ ] If a task is likely to need an agent soon, wake it提前
- [ ] Example: orchestrator starts a project → wake frontend-engineer early
- [ ] Config: `agency.pool.pre_warm: false` (opt-in)

### 5.2 Predictive Wake

- [ ] Track which agents are commonly used together
- [ ] If agent A is woken, predict agent B will be needed soon
- [ ] Wake agent B提前
- [ ] ML-lite: simple co-occurrence tracking

### 5.3 Agent Affinity

- [ ] Some agents work better together
- [ ] Config: `agency.pool.affinity: {"frontend-engineer": ["art-director", "copywriter"]}`
- [ ] When frontend-engineer wakes, also wake art-director and copywriter

### 5.4 Session Stickiness

- [ ] If an agent just completed a task, keep it alive for a bit
- [ ] Don't immediately sleep if another task might come
- [ ] Config: `agency.pool.sticky_minutes: 2`

### 5.5 Validation

- [ ] Pre-warming works
- [ ] Agent affinity wakes related agents
- [ ] Session stickiness prevents premature sleep

**Deliverable:** Smart, predictive agent pool management.

---

## Resource Estimate

| State | Memory per Agent | Total (50 agents) |
|---|---|---|
| Sleeping | ~0 MB (no process) | 0 MB |
| Waking | ~50 MB (daemon starting) | 50 MB |
| Active | ~50 MB (daemon running) | 500 MB (10 active) |
| Registry | ~1 MB (always on) | 1 MB |

**Default config:** 10 max active agents = ~500 MB RAM. Orchestrator always on = ~50 MB. Total: ~550 MB.

---

## Implementation Priority

| Phase | Priority | Effort | Impact |
|---|---|---|---|
| 1. Registry | **Critical** | Medium | Foundation |
| 2. Sleep/Wake | **High** | Medium | Core feature |
| 3. Orchestrator Integration | **High** | Medium | Automation |
| 4. Pool Manager Service | **Medium** | Large | Production |
| 5. Advanced Features | **Low** | Medium | Optimization |

---

## Questions for maintainers

1. **Registry location:** Should it be on the VPS only, or synced to GitHub?
2. **Max active agents:** 10 default OK? Or different?
3. **Idle timeout:** 5 minutes default OK?
4. **Pool manager:** Should it be a separate service or part of the orchestrator?
5. **Wake mechanism:** `hermes -p <agent> agency start` via subprocess, or direct node management?

---

## Decisions Made

1. **Registry location:** In the repo. No personal info, only agency-* namespace profiles.
2. **Agent swapping:** Automatic. Idle agents swap out when new ones needed. Max 10 active.
3. **Idle timeout:** 5 minutes default.
4. **Pool manager:** Separate systemd service on VPS.
5. **Wake mechanism:** Direct node management via Python API (not subprocess).
6. **Registry scope:** ONLY `agency-*` namespace profiles. NEVER include personal profiles (local-agent, gpt, grok, designer, git, default, vps).
