# Hermes Agency — Post-Hardening Plan

> Created: 2026-06-29
> Status: Ready to execute
> Prerequisite: `fix/repo-hardening-pass` merged to main ✅

---

## Phase 0 — Close Superseded PRs
**Owner:** Katana (manual)
**ETA:** 5 minutes

Close these PRs on GitHub (they were superseded, not auto-closed by the squash merge):

- [ ] #10 — `fix(dashboard): prevent asset path traversal` → superseded by #13
- [ ] #11 — `fix(dashboard): block asset path traversal` → superseded by #13
- [ ] #20 — `fix(pool): restrict agent wake access` → superseded by #22

Comment on each: "Superseded by #29 (hardening pass). Closing."

---

## Phase 1 — Daemon Checksum Pinning
**Owner:** `agency-backend-engineer` or Katana directly
**ETA:** 30 minutes
**Risk:** Blocks daemon auto-download until complete

The `_DAEMON_SHA256` dict in `src/agentanycast/daemon.py` is empty. Any attempt to auto-download the daemon binary will fail with "No pinned SHA-256 checksum available."

### Steps
1. Identify the current daemon release version (`_DEFAULT_DAEMON_VERSION = "0.7.2"`)
2. Download each platform binary from GitHub releases:
   - `agentanycastd-linux-amd64`
   - `agentanycastd-linux-arm64`
   - `agentanycastd-darwin-arm64`
   - `agentanycastd-darwin-amd64`
   - `agentanycastd-windows-amd64.exe`
3. Compute SHA-256 for each
4. Populate `_DAEMON_SHA256` in `daemon.py`
5. Add a test verifying the dict is non-empty for current version
6. Commit + PR

---

## Phase 2 — Activate Core Agents (Smoke Test)
**Owner:** Katana
**ETA:** 15 minutes
**Risk:** Low — local-only testing

Goal: Verify the hardened defaults work end-to-end with at least one agent.

### Steps
1. Wake `agency-orchestrator` via pool manager
2. Verify loopback binding (pool API on 127.0.0.1)
3. Verify bearer token auth rejects unauthenticated POST
4. Verify wake rejects unregistered agent names
5. Send a test task with default `safe` tool_access
6. Confirm delegation uses safe toolset (`web, search, skills, memory, session_search`)
7. Document any issues found

---

## Phase 3 — Merge PR #8 (Fabric Authz)
**Owner:** `agency-code-reviewer` (review) + Katana (merge decision)
**ETA:** 20 minutes
**Risk:** Medium — Fabric app scope, not agency core

PR #8 adds agent JWT validation to Fabric plugin routes. Valid security fix for the Fabric app.

### Steps
1. Review PR #8 diff against current main
2. Check for conflicts
3. Run Fabric app tests if available
4. Merge if clean, or port manually if conflicts

---

## Phase 4 — Dashboard Feature Work
**Owner:** `agency-frontend-engineer` + `agency-ux-designer`
**ETA:** Hackathon scope
**Priority:** High

The dashboard is the primary user interface for Hermes Agency. Key areas:

### 4a — Dispatch UI
- [ ] Task creation form with agent selector
- [ ] Skill-based routing suggestions
- [ ] Real-time task status updates

### 4b — Kanban Views
- [ ] Board view per department
- [ ] Drag-and-drop task management
- [ ] Filter by agent, status, priority

### 4c — Model-Set Management
- [ ] View current model assignments
- [ ] Override models per agent
- [ ] Cost/usage tracking

### 4d — Agent Roster
- [ ] Online/offline status indicators
- [ ] Wake controls
- [ ] Skill/capability display

---

## Phase 5 — Integration Testing
**Owner:** `agency-qa-lead` + `agency-integration-engineer`
**ETA:** 1-2 hours
**Risk:** Medium — requires multiple agents online

### Test Matrix
| Scenario | Agents Needed | Validates |
|----------|--------------|-----------|
| Simple delegation | orchestrator + 1 specialist | Basic task routing |
| Multi-agent workflow | orchestrator + 3 specialists | Kanban + handoff |
| Offline wake + queue | 1 offline agent | Pool manager wake |
| Safe tool_access | any agent | Toolset restriction |
| Dashboard dispatch | orchestrator + dashboard | UI → task pipeline |
| Cross-network | 2 agents via relay | P2P transport |

---

## Execution Order

```
Phase 0 (close PRs) ──→ Phase 1 (checksums) ──→ Phase 2 (smoke test)
                                                        │
                                              ┌─────────┴─────────┐
                                              ▼                   ▼
                                        Phase 3 (PR #8)    Phase 4 (dashboard)
                                              │                   │
                                              └─────────┬─────────┘
                                                        ▼
                                              Phase 5 (integration)
```

Phases 0-1 are blockers. Phases 2-3 can run in parallel. Phase 4 is the hackathon main track. Phase 5 validates everything.

---

## Open Questions

1. **Agent profiles**: The 83-agent roster references profiles that don't exist locally yet. Where should the profile definitions live? (`hermes-agency/default_staff/profiles/` or generated at runtime?)

2. **Model assignments**: What model/provider should the agency agents use? The roster shows `gpt-5.5 / openai-codex` — is that the intended default?

3. **Dashboard build**: Is the `web/agency-dashboard/` build artifact committed, or does it need to be built from source on every deploy?

4. **Relay infrastructure**: Is there a relay server running for cross-network testing, or should we test local-only first?
