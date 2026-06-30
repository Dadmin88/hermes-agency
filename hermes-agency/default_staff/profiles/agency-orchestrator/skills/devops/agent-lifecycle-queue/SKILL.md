---
name: agent-lifecycle-queue
description: "Slot-based agent lifecycle queue with automatic wake/sleep handoff. Controls how many agents are online simultaneously to prevent OOM. Agents queue for slots, get woken when a slot opens, and auto-sleep after completing work."
version: "1.0.0"
---

## Problem

The VPS has ~7GB available RAM. Each agent daemon costs ~600MB. Max safe concurrent agents: ~5-6. With 98 registered agents, uncontrolled wake = OOM crash.

## Architecture

**Queue state:** `~/.hermes/.agency/agent_queue.json`

```json
{
  "max_slots": 5,
  "permanent": ["agency-orchestrator"],
  "slots": {
    "agency-orchestrator": {"since": "ISO", "reason": "permanent"},
    "agency-business-analyst": {"since": "ISO", "task_id": "...", "expires_at": "ISO"}
  },
  "queue": [
    {"name": "agency-compliance-reviewer", "queued_at": "ISO", "priority": 0, "reason": "task"}
  ]
}
```

## Rules

1. **Permanent agents** (orchestrator, git-steward) never get evicted
2. **Slot limit** is enforced — wake is refused if all slots occupied
3. **Queue is FIFO by priority** — higher priority jumps ahead
4. **Handoff on completion** — when an agent finishes, it calls `queue_handoff()` which wakes the next in queue
5. **Idle timeout** — agents with no active task for >5 minutes get reclaimed
6. **Stale cleanup** — agents that crash/die get their slots freed immediately

## Scripts

All scripts are in `scripts/` subdirectory. The main orchestrator calls them via `terminal()`.

### queue_check.py
Check slot availability. Returns `available_slots`, `occupied`, `queue_length`.

### queue_request.py
Request a slot for an agent. If slot available → wake immediately. If full → enqueue.

### queue_handoff.py
Called when an agent finishes work. Frees the slot, wakes next in queue.

### queue_reclaim.py
Checks for idle/expired agents and reclaims their slots. Run by watchdog cron.

### queue_status.py
Print human-readable queue status for reporting.

## Integration

### When orchestrator needs to delegate:
1. Call `queue_request.py --name agency-XXX --reason task`
2. If slot available → agent wakes → send task
3. If full → task queued, agent wakes when slot opens

### When agent finishes work:
1. Agent's runner detects task completion
2. Calls `queue_handoff.py --name agency-XXX`
3. Next queued agent wakes up

### Watchdog cron (every 2 minutes):
1. `queue_reclaim.py` — kills idle agents, frees slots
2. `queue_handoff.py` — wakes next in queue if slot freed

## VPS Resource Constraints

- **RAM:** 11GB total, ~7GB available → 5 concurrent agent slots
- **CPU:** 6 cores — adequate for 5 agents
- **Disk:** 49GB free — plenty for workspace
