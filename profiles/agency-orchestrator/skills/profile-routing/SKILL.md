---
name: profile-routing
description: Route Agency work to the named Hermes profile whose professional ownership best matches the required outcome, using role descriptions, boundaries, evidence needs, and the smallest capable team.
---
# Profile Routing

Use when assigning or reassigning work across Hermes Agency profiles.

## Procedure
1. Start from the outcome the task must produce, not from keywords in its title. Identify the decision, artifact, implementation, review, or validation responsibility that actually needs an owner.
2. Inspect the available named profile descriptions and relevant Agency role boundaries before assigning. Route by professional ownership and expected deliverable rather than by superficial vocabulary overlap.
3. Prefer the narrowest specialist that fully owns the work. Use a broader role only when the task genuinely spans that broader role's authority or a narrower specialist is unavailable.
4. Distinguish neighboring roles explicitly before routing ambiguous work. Examples include Product Manager vs Technical Lead, Software Architect vs Systems Architect, Backend vs Data/Database/Infrastructure, Product Designer vs UI/UX/Brand, Code Reviewer vs QA vs Security Reviewer, and Marketing Strategy vs Copy/Content/Social.
5. Use the smallest capable team. Add another profile only when it contributes distinct expertise, independent validation, or a real downstream deliverable.
6. When operating through Hermes Kanban, assign the task to the named profile and preserve the task body, constraints, dependencies, attachments, and acceptance evidence needed by that worker. Use the `kanban_*` tools rather than shelling out to the human CLI.
7. If a task contains multiple independently owned outcomes, decompose it before routing instead of assigning a multi-role blob to one specialist.
8. Re-route only when evidence shows the current owner lacks the authority or specialty required. Preserve the completed work and handoff context rather than restarting blindly.
9. If no installed profile owns the capability cleanly, identify the closest legitimate owner and the missing specialization explicitly. Do not invent a profile name or silently expand another role's authority.

## Decision rules
- Ownership beats keyword matching.
- Named Agency roles remain accountable even if they use bounded within-lane subagents internally.
- A reviewer is not the implementer, and an implementer does not become the independent reviewer of its own work merely because it can inspect it.
- Cross-functional ambiguity should be resolved by splitting decisions according to authority, not by choosing the most senior-sounding title.

## Quality gate
Routing is correct when each task has one accountable named owner whose role genuinely owns the requested outcome, neighboring-role confusion has been resolved, the team is no larger than necessary, and the worker receives enough context to complete and validate its assignment without inheriting unrelated authority.