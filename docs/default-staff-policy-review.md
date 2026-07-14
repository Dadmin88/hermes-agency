# Default Staff Incoming-Task Policy Review

**Reviewed:** 2026-07-14
**Profiles:** 83
**Scope:** packaged `hermes-agency/default_staff/profiles/*/profile.yaml`

## Decision

Retain the current policy deliberately:

- `agency.allow_remote_tasks: false` on every packaged profile. Remote execution is disabled by default.
- `agency.incoming.tool_access: full` on every packaged specialist. This is intentional for full specialist handoffs **only after** an operator explicitly enables remote tasks for that profile.
- Progress forwarding is not set in packaged profiles and therefore follows the runtime default (`false`).
- No profile receives remote execution merely by being installed, auto-started, or assigned a full incoming tool scope.

The combination is safe by default because the execution gate is closed. Changing all specialists to `safe` would contradict the existing `test_default_staff.py` contract and prevent intended specialist handoffs. The security-sensitive transition is enabling `allow_remote_tasks`; operators must review the profile's tools and credentials before doing so.

## Required enablement review

Before changing any profile to `allow_remote_tasks: true`:

1. Confirm the sender trust/allowlist policy.
2. Review that profile's toolset and credential exposure.
3. Choose `safe`, `full`, or `none` explicitly rather than inheriting blindly.
4. Decide whether progress updates may expose task content.
5. Run an authorization-negative test and a bounded terminal task.
6. Record the approving operator and rollback (`allow_remote_tasks: false`).

## Profile-by-profile decision table

| Profile | Remote tasks | Incoming tools | Progress | Decision |
|---|---:|---|---:|---|
| `agency-accessibility-reviewer` | false | `full` | false | Retain; remote gate closed |
| `agency-ai-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-analytics-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-art-director` | false | `full` | false | Retain; remote gate closed |
| `agency-asset-artist` | false | `full` | false | Retain; remote gate closed |
| `agency-audio-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-automation-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-backend-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-brand-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-business-analyst` | false | `full` | false | Retain; remote gate closed |
| `agency-chief-of-staff` | false | `full` | false | Retain; remote gate closed |
| `agency-code-reviewer` | false | `full` | false | Retain; remote gate closed |
| `agency-community-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-competitive-analyst` | false | `full` | false | Retain; remote gate closed |
| `agency-compliance-reviewer` | false | `full` | false | Retain; remote gate closed |
| `agency-content-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-copywriter` | false | `full` | false | Retain; remote gate closed |
| `agency-creative-director` | false | `full` | false | Retain; remote gate closed |
| `agency-customer-success` | false | `full` | false | Retain; remote gate closed |
| `agency-data-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-database-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-design-reviewer` | false | `full` | false | Retain; remote gate closed |
| `agency-design-systems-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-devops-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-dialogue-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-docs-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-editor-in-chief` | false | `full` | false | Retain; remote gate closed |
| `agency-email-marketer` | false | `full` | false | Retain; remote gate closed |
| `agency-environment-artist` | false | `full` | false | Retain; remote gate closed |
| `agency-finance-ops` | false | `full` | false | Retain; remote gate closed |
| `agency-frontend-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-fullstack-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-game-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-git-steward` | false | `full` | false | Retain; remote gate closed |
| `agency-godot-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-growth-marketer` | false | `full` | false | Retain; remote gate closed |
| `agency-infrastructure-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-integration-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-knowledge-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-launch-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-legal-ops` | false | `full` | false | Retain; remote gate closed |
| `agency-level-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-lore-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-market-researcher` | false | `full` | false | Retain; remote gate closed |
| `agency-marketing-strategist` | false | `full` | false | Retain; remote gate closed |
| `agency-monetization-strategist` | false | `full` | false | Retain; remote gate closed |
| `agency-motion-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-onboarding-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-operations-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-orchestrator` | false | `full` | false | Retain; remote gate closed |
| `agency-partnerships-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-performance-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-platform-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-procurement-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-product-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-product-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-product-strategist` | false | `full` | false | Retain; remote gate closed |
| `agency-project-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-public-relations` | false | `full` | false | Retain; remote gate closed |
| `agency-qa-lead` | false | `full` | false | Retain; remote gate closed |
| `agency-qa-tester` | false | `full` | false | Retain; remote gate closed |
| `agency-red-team` | false | `full` | false | Retain; remote gate closed |
| `agency-release-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-release-notes-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-requirements-analyst` | false | `full` | false | Retain; remote gate closed |
| `agency-scriptwriter` | false | `full` | false | Retain; remote gate closed |
| `agency-scrum-master` | false | `full` | false | Retain; remote gate closed |
| `agency-security-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-security-reviewer` | false | `full` | false | Retain; remote gate closed |
| `agency-seo-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-social-media-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-software-architect` | false | `full` | false | Retain; remote gate closed |
| `agency-support-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-systems-architect` | false | `full` | false | Retain; remote gate closed |
| `agency-technical-artist` | false | `full` | false | Retain; remote gate closed |
| `agency-technical-lead` | false | `full` | false | Retain; remote gate closed |
| `agency-technical-writer` | false | `full` | false | Retain; remote gate closed |
| `agency-tools-engineer` | false | `full` | false | Retain; remote gate closed |
| `agency-traffic-manager` | false | `full` | false | Retain; remote gate closed |
| `agency-training-specialist` | false | `full` | false | Retain; remote gate closed |
| `agency-ui-ux-designer` | false | `full` | false | Retain; remote gate closed |
| `agency-user-researcher` | false | `full` | false | Retain; remote gate closed |
| `agency-worldbuilder` | false | `full` | false | Retain; remote gate closed |

## Verification

The review script asserted all 83 packaged profiles have remote execution disabled and the intended full specialist handoff scope. The repository contract in `hermes-agency/tests/test_default_staff.py` verifies the same tool-access intent.
