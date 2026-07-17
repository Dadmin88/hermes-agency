# Agency Night Shift playbook

This is the canonical headless autonomous-workflow guide for Hermes Agency. Use it when a worker, orchestrator, or operator needs a single traceable loop from task intake to validated handoff.

This playbook does not replace `AGENTS.md`, `hermes-agency/default_staff/STAFF_CONTRACT.md`, or a profile’s `ROUTING.md`. Those files remain authoritative for role boundaries, safety rules, and task ownership.

## Source of truth

- Use Kanban and Fabric artifacts as the durable trace of work.
- If the chat, task card, and repository disagree, treat that as a problem to reconcile before continuing.
- Do not rely on private notes or ad hoc messages as the final record.
- Do not start autonomous git, commit, push, merge, rebase, or deploy behavior unless the operator explicitly authorizes it or a separate steward task owns that step.

## Load context first

Before making changes, read the smallest set of sources that actually governs the task:

1. The active Kanban card and its comments.
2. The profile instructions in `ROUTING.md` and `SOUL.md`.
3. `AGENTS.md` for repository-wide worker protocol.
4. The narrowest relevant docs or skills for the task.

Load the skills the task actually needs. When the work touches docs or memory updates, include `doc-sync`. For prose-heavy writing tasks, include `content-style-guide` when it is available. Load domain-specific skills when the task touches a specialized area, such as Hermes configuration or transport behavior.

## Night Shift loop

1. Intake the task.
   - Read the card, comments, parent handoffs, and workspace notes.
   - Restate the goal in one line.
   - Confirm the workspace is the one assigned to the card.

2. Select one active objective.
   - Keep one card, one workspace, and one primary outcome in flight.
   - If the card is already blocked by missing input, add the reason to Kanban and stop.
   - If a new follow-up is needed, create a child card instead of silently widening scope.

3. Load only the needed context.
   - Read the files that govern the current change.
   - Prefer existing guidance over inventing new process.
   - Avoid pulling in unrelated docs or skills.

4. Execute in small, verifiable steps.
   - Make the smallest useful change set.
   - Keep comments and heartbeats meaningful and brief.
   - If the task runs long, send periodic Kanban heartbeats that describe real progress, not filler.

5. Validate before claiming success.
   - Run the narrowest check that proves the change.
   - For docs, read the changed file back and confirm links, wording, and references.
   - For code, run the relevant tests or lint checks for the touched area.
   - Fix the root cause if validation fails.
   - Use `docs/qa-validation-ladder.md` to choose the minimum rung that supports the claim you plan to make.

6. Hand off for review when needed.
   - If the work is complete but still needs human review, say so explicitly in Kanban.
   - Include changed files, checks run, and any residual risk.
   - Do not present review-needed work as finished.

7. Wrap up cleanly.
   - Record the final state in Kanban.
   - Keep the final report short and factual.
   - Mention deliverables, validation, and open issues in one pass.

## Stop conditions

Stop and block, rather than guessing, when any of these apply:

- Missing credentials or access required to proceed safely.
- Production, runtime, or deploy approval is needed.
- Git state is unsafe, ambiguous, or outside the authorized workspace.
- A reviewer has rejected the work and the next action needs a human decision.
- The workspace is stale, conflicting, or no longer matches the task.
- The task depends on a live Keryx end-to-end phase gate that has not been explicitly cleared.

When blocking, add the specific blocker and the smallest next action that would unblock it.

## Token-conscious operating rules

- Prefer one concise Kanban update over multiple chat messages.
- Use heartbeats only when they add new progress information.
- Summarize related findings together instead of sending one-line status noise.
- Keep final reports short, with the artifact path and validation result up front.

## Final reporting template

When the task is complete, report:

- Status: completed or blocked
- Deliverables: file paths or `none`
- Summary: what changed
- Decisions: key assumptions or tradeoffs
- Verification: what was checked and the outcome
- Issues: any remaining risk or follow-up

## Related references

- `AGENTS.md`
- `hermes-agency/default_staff/STAFF_CONTRACT.md`
- `hermes-agency/default_staff/profiles/agency-orchestrator/ROUTING.md`
- `docs/keryx-cross-node-boundary.md`
- `docs/qa-validation-ladder.md`
- `docs/phase17-agency-integration.md`
- `docs/agency-moa.md`
- `docs/troubleshooting.md`
