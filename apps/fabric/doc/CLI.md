# CLI Reference

Hermes Fabric CLI now supports both:

- instance setup/diagnostics (`onboard`, `doctor`, `configure`, `env`, `allowed-hostname`, `env-lab`)
- control-plane client operations (issues, approvals, agents, activity, dashboard)

## Base Usage

Use repo script in development:

```sh
pnpm hermes-fabric --help
```

First-time local bootstrap + run:

```sh
pnpm hermes-fabric run
```

Choose local instance:

```sh
pnpm hermes-fabric run --instance dev
```

## Deployment Modes

Mode taxonomy and design intent are documented in `doc/DEPLOYMENT-MODES.md`.

Current CLI behavior:

- `hermes-fabric onboard` and `hermes-fabric configure --section server` set deployment mode in config
- server onboarding/configure ask for reachability intent and write `server.bind`
- `hermes-fabric run --bind <loopback|lan|tailnet>` passes a quickstart bind preset into first-run onboarding when config is missing
- runtime can override mode with `HERMES_FABRIC_DEPLOYMENT_MODE`
- `hermes-fabric run` and `hermes-fabric doctor` still do not expose a direct low-level `--mode` flag

Canonical behavior is documented in `doc/DEPLOYMENT-MODES.md`.

Allow an authenticated/private hostname (for example custom Tailscale DNS):

```sh
pnpm hermes-fabric allowed-hostname dotta-macbook-pro
```

Bring up the default local SSH fixture for environment testing:

```sh
pnpm hermes-fabric env-lab up
pnpm hermes-fabric env-lab doctor
pnpm hermes-fabric env-lab status --json
pnpm hermes-fabric env-lab down
```

All client commands support:

- `--data-dir <path>`
- `--api-base <url>`
- `--api-key <token>`
- `--context <path>`
- `--profile <name>`
- `--json`

Company-scoped commands also support `--company-id <id>`.

API base resolution order:

1. `--api-base <url>`
2. `HERMES_FABRIC_API_URL`
3. selected context profile `apiBase`
4. local Hermes Fabric config server port
5. `http://localhost:3100`

Connection failures include the attempted URL and a `GET /api/health` check hint.

## Connect Wizard

```sh
pnpm hermes-fabric connect
```

`connect` confirms the resolved API base, verifies `GET /api/health`, authenticates board access when needed, and saves a persona-aware profile:

- `persona=board` for board operator profiles
- `persona=agent` with `agentId` and `agentName` for agent profiles

Profiles store token env-var names, not plaintext tokens. The wizard prints shell exports for the newly created token.

Use `--data-dir` on any CLI command to isolate all default local state (config/context/db/logs/storage/secrets) away from `~/.hermes-fabric`:

```sh
pnpm hermes-fabric run --data-dir ./tmp/fabric-dev
pnpm hermes-fabric issue list --data-dir ./tmp/fabric-dev
```

## Context Profiles

Store local defaults in `~/.hermes-fabric/context.json`:

```sh
pnpm hermes-fabric context set --api-base http://localhost:3100 --company-id <company-id>
pnpm hermes-fabric context set --persona agent --agent-id <agent-id> --api-key-env-var-name HERMES_FABRIC_API_KEY
pnpm hermes-fabric context show
pnpm hermes-fabric context list
pnpm hermes-fabric context use default
```

To avoid storing secrets in context, set `apiKeyEnvVarName` and keep the key in env:

```sh
pnpm hermes-fabric context set --api-key-env-var-name HERMES_FABRIC_API_KEY
export HERMES_FABRIC_API_KEY=...
```

## Company Commands

```sh
pnpm hermes-fabric company list
pnpm hermes-fabric company get <company-id>
pnpm hermes-fabric company current [--company-id <company-id>]
pnpm hermes-fabric company stats
pnpm hermes-fabric company create --payload-json '{...}'
pnpm hermes-fabric company update <company-id> --payload-json '{...}'
pnpm hermes-fabric company branding:update <company-id> --payload-json '{...}'
pnpm hermes-fabric company archive <company-id>
pnpm hermes-fabric company export <company-id> --out ./company --include company,agents,projects,issues,skills
pnpm hermes-fabric company export:preview <company-id> --payload-json '{...}'
pnpm hermes-fabric company export:api <company-id> --payload-json '{...}'
pnpm hermes-fabric company import ./company --target new --new-company-name "Imported Company"
pnpm hermes-fabric company import:preview <company-id> --payload-json '{...}'
pnpm hermes-fabric company import:apply <company-id> --payload-json '{...}'
pnpm hermes-fabric company delete <company-id-or-prefix> --yes --confirm <same-id-or-prefix>
```

Examples:

```sh
pnpm hermes-fabric company delete PAP --yes --confirm PAP
pnpm hermes-fabric company delete 5cbe79ee-acb3-4597-896e-7662742593cd --yes --confirm 5cbe79ee-acb3-4597-896e-7662742593cd
```

Notes:

- With agent authentication, `company list` and `company current` are
  agent-safe company selectors. `company list` first tries the board-wide list;
  if that is forbidden, it uses `--company-id`, `HERMES_FABRIC_COMPANY_ID`, context,
  or `/api/agents/me` and then reads only that scoped company.
- `company create` requires board/instance-admin authentication because it is
  an instance-wide setup command.
- Deletion is server-gated by `HERMES_FABRIC_ENABLE_COMPANY_DELETION`.
- With agent authentication, company deletion is company-scoped. Use the current company ID/prefix (for example via `--company-id` or `HERMES_FABRIC_COMPANY_ID`), not another company.

## Issue Commands

```sh
pnpm hermes-fabric issue list --company-id <company-id> [--status todo,in_progress] [--assignee-agent-id <agent-id>] [--match text]
pnpm hermes-fabric issue get <issue-id-or-identifier>
pnpm hermes-fabric issue create --company-id <company-id> --title "..." [--description "..."] [--status todo] [--priority high]
pnpm hermes-fabric issue update <issue-id> [--status in_progress] [--comment "..."]
pnpm hermes-fabric issue delete <issue-id> --yes
pnpm hermes-fabric issue comment <issue-id> --body "..." [--reopen]
pnpm hermes-fabric issue comments <issue-id> [--limit 50]
pnpm hermes-fabric issue comment:get <issue-id> <comment-id>
pnpm hermes-fabric issue comment:delete <issue-id> <comment-id>
pnpm hermes-fabric issue runs <issue-id-or-identifier>
pnpm hermes-fabric issue live-runs <issue-id-or-identifier>
pnpm hermes-fabric issue active-run <issue-id-or-identifier>
pnpm hermes-fabric issue heartbeat-context <issue-id>
pnpm hermes-fabric issue checkout <issue-id> --agent-id <agent-id> [--expected-statuses todo,backlog,blocked]
pnpm hermes-fabric issue release <issue-id>
pnpm hermes-fabric issue force-release <issue-id>
```

Issue subresources are exposed as Hermes Fabric API wrappers. Commands that map to broad server schemas accept JSON payloads and validate them with shared schemas before sending.

```sh
pnpm hermes-fabric issue child:create <issue-id> --payload-json '{"title":"Child task"}'
pnpm hermes-fabric issue approvals <issue-id>
pnpm hermes-fabric issue approval:link <issue-id> <approval-id>
pnpm hermes-fabric issue approval:unlink <issue-id> <approval-id>
pnpm hermes-fabric issue read <issue-id>
pnpm hermes-fabric issue unread <issue-id>
pnpm hermes-fabric issue archive <issue-id>
pnpm hermes-fabric issue unarchive <issue-id>
pnpm hermes-fabric issue recovery-actions <issue-id>
pnpm hermes-fabric issue recovery:resolve <issue-id> --outcome restored --source-issue-status todo
```

```sh
pnpm hermes-fabric issue documents <issue-id> [--include-system]
pnpm hermes-fabric issue document:get <issue-id> <key>
pnpm hermes-fabric issue document:put <issue-id> <key> --body-file ./plan.md [--title Plan]
pnpm hermes-fabric issue document:lock <issue-id> <key>
pnpm hermes-fabric issue document:unlock <issue-id> <key>
pnpm hermes-fabric issue document:revisions <issue-id> <key>
pnpm hermes-fabric issue document:restore <issue-id> <key> <revision-id>
pnpm hermes-fabric issue document:delete <issue-id> <key>
```

```sh
pnpm hermes-fabric issue work-products <issue-id>
pnpm hermes-fabric issue work-product:create <issue-id> --payload-json '{"type":"pull_request","provider":"github","title":"PR"}'
pnpm hermes-fabric issue work-product:update <work-product-id> --payload-json '{"status":"archived"}'
pnpm hermes-fabric issue work-product:delete <work-product-id>
pnpm hermes-fabric issue interactions <issue-id>
pnpm hermes-fabric issue interaction:create <issue-id> --payload-json '{"kind":"request_confirmation","payload":{"version":1,"prompt":"Continue?"}}'
pnpm hermes-fabric issue interaction:accept <issue-id> <interaction-id> [--selected-client-keys key1,key2]
pnpm hermes-fabric issue interaction:reject <issue-id> <interaction-id> [--reason "..."]
pnpm hermes-fabric issue interaction:respond <issue-id> <interaction-id> --answers-json '[{"questionId":"q1","optionIds":["yes"]}]'
pnpm hermes-fabric issue interaction:cancel <issue-id> <interaction-id> [--reason "..."]
```

```sh
pnpm hermes-fabric issue tree-state <issue-id>
pnpm hermes-fabric issue tree-preview <issue-id> --payload-json '{"mode":"pause"}'
pnpm hermes-fabric issue tree-holds <issue-id> [--status active] [--include-members]
pnpm hermes-fabric issue tree-hold:create <issue-id> --payload-json '{"mode":"pause","reason":"review"}'
pnpm hermes-fabric issue tree-hold:get <issue-id> <hold-id>
pnpm hermes-fabric issue tree-hold:release <issue-id> <hold-id> [--payload-json '{"reason":"done"}']
pnpm hermes-fabric issue attachments <issue-id>
pnpm hermes-fabric issue attachment:upload <issue-id> --company-id <company-id> --file ./artifact.txt
pnpm hermes-fabric issue attachment:download <attachment-id> [--out ./artifact.txt]
pnpm hermes-fabric issue attachment:delete <attachment-id>
pnpm hermes-fabric issue label:list --company-id <company-id>
pnpm hermes-fabric issue label:create --company-id <company-id> --name bug --color '#ff0000'
pnpm hermes-fabric issue label:delete <label-id>
pnpm hermes-fabric issue feedback:votes <issue-id>
pnpm hermes-fabric issue feedback:vote <issue-id> --payload-json '{"targetType":"issue_comment","targetId":"...","vote":"up"}'
```

## Project Commands

```sh
pnpm hermes-fabric project list --company-id <company-id>
pnpm hermes-fabric project get <project-id-or-shortname> [--company-id <company-id>]
pnpm hermes-fabric project create --company-id <company-id> --name "Launch Site" [--goal-ids <id1,id2>] [--lead-agent-id <id>]
pnpm hermes-fabric project update <project-id-or-shortname> [--status in_progress] [--company-id <company-id>]
pnpm hermes-fabric project delete <project-id-or-shortname> --yes [--company-id <company-id>]
```

Advanced project fields accept JSON:

```sh
pnpm hermes-fabric project create --company-id <company-id> --name "Ops" --env-json '{"OPENAI_API_KEY":{"kind":"secret","secretName":"openai-api-key"}}'
pnpm hermes-fabric project update <project-id> --execution-workspace-policy-json '{"enabled":true,"defaultMode":"shared_workspace"}'
```

## Goal Commands

```sh
pnpm hermes-fabric goal list --company-id <company-id>
pnpm hermes-fabric goal get <goal-id>
pnpm hermes-fabric goal create --company-id <company-id> --title "Grow revenue" [--level company] [--status active]
pnpm hermes-fabric goal update <goal-id> [--title "..."] [--status achieved]
pnpm hermes-fabric goal delete <goal-id> --yes
```

## Agent Commands

```sh
pnpm hermes-fabric agent list --company-id <company-id>
pnpm hermes-fabric agent get <agent-id>
pnpm hermes-fabric agent create --company-id <company-id> --payload-json '{"name":"Builder","adapterType":"codex_local"}'
pnpm hermes-fabric agent hire --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric agent update <agent-id> --payload-json '{"title":"Senior Builder"}'
pnpm hermes-fabric agent delete <agent-id> --yes
pnpm hermes-fabric agent me
pnpm hermes-fabric agent inbox
pnpm hermes-fabric agent inbox-mine --user-id <board-user-id>
pnpm hermes-fabric agent wake <agent-id-or-shortname> [--company-id <company-id>] [--reason "..."] [--payload '{"issueId":"..."}']
pnpm hermes-fabric agent pause <agent-id>
pnpm hermes-fabric agent resume <agent-id>
pnpm hermes-fabric agent approve <agent-id>
pnpm hermes-fabric agent terminate <agent-id>
pnpm hermes-fabric agent heartbeat:invoke <agent-id>
pnpm hermes-fabric agent claude-login <agent-id>
pnpm hermes-fabric agent local-cli <agent-id-or-shortname> --company-id <company-id>
```

Agent configuration and runtime endpoints:

```sh
pnpm hermes-fabric agent permissions:update <agent-id> --payload-json '{"canCreateAgents":true,"canCreateSkills":true,"canAssignTasks":true}'
pnpm hermes-fabric agent configuration <agent-id>
pnpm hermes-fabric agent config-revisions <agent-id>
pnpm hermes-fabric agent config-revision:get <agent-id> <revision-id>
pnpm hermes-fabric agent config-revision:rollback <agent-id> <revision-id>
pnpm hermes-fabric agent runtime-state <agent-id>
pnpm hermes-fabric agent runtime-state:reset-session <agent-id> [--task-key <key>]
pnpm hermes-fabric agent task-sessions <agent-id>
pnpm hermes-fabric agent skills <agent-id>
pnpm hermes-fabric agent skills:sync <agent-id> --desired-skills fabric,github
pnpm hermes-fabric agent instructions-path:update <agent-id> --payload-json '{"path":"/path/to/AGENTS.md"}'
pnpm hermes-fabric agent instructions-bundle <agent-id>
pnpm hermes-fabric agent instructions-bundle:update <agent-id> --payload-json '{"mode":"managed"}'
pnpm hermes-fabric agent instructions-file:get <agent-id> --path AGENTS.md
pnpm hermes-fabric agent instructions-file:put <agent-id> --path AGENTS.md --content-file ./AGENTS.md
pnpm hermes-fabric agent instructions-file:delete <agent-id> --path AGENTS.md
```

`agent local-cli` is the quickest way to run local Claude/Codex manually as a Hermes Fabric agent:

- creates a new long-lived agent API key
- installs missing Hermes Fabric skills into `~/.codex/skills` and `~/.claude/skills`
- prints `export ...` lines for `HERMES_FABRIC_API_URL`, `HERMES_FABRIC_COMPANY_ID`, `HERMES_FABRIC_AGENT_ID`, and `HERMES_FABRIC_API_KEY`

Example for shortname-based local setup:

```sh
pnpm hermes-fabric agent local-cli codexcoder --company-id <company-id>
pnpm hermes-fabric agent local-cli claudecoder --company-id <company-id>
```

## Token Commands

Agent API keys are scoped to one company and one agent. Plaintext tokens are printed once at creation.

```sh
pnpm hermes-fabric token agent create --company-id <company-id> --agent <agent-id-or-name> --name external-worker
pnpm hermes-fabric token agent list --company-id <company-id> --agent <agent-id-or-name>
pnpm hermes-fabric token agent revoke --company-id <company-id> --agent <agent-id-or-name> <key-id>
```

Named board API keys use the board authorization model, support revocation and expiration metadata, and are audited server-side.

```sh
pnpm hermes-fabric token board create --company-id <company-id> --name external-admin
pnpm hermes-fabric token board create --name short-lived --ttl-days 7
pnpm hermes-fabric token board list
pnpm hermes-fabric token board revoke <key-id>
```

## Run Commands

`hermes-fabric run` without a subcommand still bootstraps and starts a local Hermes Fabric instance. The subcommands below inspect and control API heartbeat runs.

```sh
pnpm hermes-fabric run list --company-id <company-id> [--agent-id <agent-id>] [--limit 50]
pnpm hermes-fabric run live --company-id <company-id> [--limit 50] [--min-count 0]
pnpm hermes-fabric run get <run-id>
pnpm hermes-fabric run events <run-id> [--after-seq 0] [--limit 200]
pnpm hermes-fabric run log <run-id> [--offset 0] [--limit-bytes 16384] [--text]
pnpm hermes-fabric run cancel <run-id>
pnpm hermes-fabric run issues <run-id>
pnpm hermes-fabric run workspace-operations <run-id>
pnpm hermes-fabric run workspace-log <operation-id> [--offset 0] [--limit-bytes 16384] [--text]
pnpm hermes-fabric run watchdog-decision <run-id> --decision continue [--reason "..."]
```

## Routine Commands

`hermes-fabric routines disable-all` remains the local maintenance command. The singular `routine` group maps to the REST API.

```sh
pnpm hermes-fabric routine list --company-id <company-id> [--project-id <project-id>]
pnpm hermes-fabric routine create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric routine get <routine-id>
pnpm hermes-fabric routine update <routine-id> --payload-json '{...}'
pnpm hermes-fabric routine revisions <routine-id>
pnpm hermes-fabric routine revision:restore <routine-id> <revision-id>
pnpm hermes-fabric routine runs <routine-id> [--limit 50]
pnpm hermes-fabric routine run <routine-id> [--payload-json '{...}']
pnpm hermes-fabric routine trigger:create <routine-id> --payload-json '{...}'
pnpm hermes-fabric routine trigger:update <trigger-id> --payload-json '{...}'
pnpm hermes-fabric routine trigger:delete <trigger-id>
pnpm hermes-fabric routine trigger:rotate-secret <trigger-id>
pnpm hermes-fabric routine trigger:fire <public-id> [--payload-json '{...}']
```

## Prompt Handoff

Prompt handoff creates Hermes Fabric work. It does not create a chat session.

```sh
pnpm hermes-fabric agent-prompt <agent-name-or-id> <agent-api-key> "Prompt here"
pnpm hermes-fabric agent prompt --agent <agent-name-or-id> --api-key-env HERMES_FABRIC_API_KEY "Prompt here"
pnpm hermes-fabric agent prompt --profile my-agent "Prompt here"
pnpm hermes-fabric board prompt --company-id <company-id> --agent <agent-name-or-id> "Prompt here"
```

By default the command creates a `todo` issue assigned to the target agent and wakes the agent. Use `--issue <issue-id>` to add a comment to existing work, and `--no-wake` to skip the wakeup.

## Skills Commands

`hermes-fabric skills` covers three distinct operations:

1. **Company install** — adds or updates a row in `company_skills` for the
   whole company. This is what `skills install`, `skills import`, `skills create`,
   and `skills scan-projects` do.
2. **Agent attach** — replaces an agent's *desired* company skill set
   (`skills agent sync`/`clear`). This is a desired-state operation on the
   agent's adapter config; it does not change the company library.
3. **Adapter runtime sync** — the adapter reconciles the desired skill set
   with files on disk and reports an `AgentSkillSnapshot` (`skills agent list`).
   `skills agent sync` triggers this automatically after updating desired state.

Required Hermes Fabric runtime skills (heartbeat, etc.) remain server-enforced and
are added on top of whatever the desired set names.

Company skill mutations (`skills install`, `skills import`, `skills create`, and
`skills scan-projects`) require board authentication, an explicit `skills:create`
grant, or an agent whose permissions keep `canCreateSkills` enabled. They do not
require `agents:create` unless the command also creates agents.

### Catalog (app-shipped skills)

The Hermes Fabric app ships a curated catalog under `@hermes-fabric/skills-catalog`.
Browse and inspect commands never mutate company state; `install` adds a catalog
skill to the company library.

```sh
pnpm hermes-fabric skills browse [--kind bundled|optional] [--category <slug>] [--query <text>]
pnpm hermes-fabric skills search "<text>" [--kind bundled|optional] [--category <slug>]
pnpm hermes-fabric skills inspect <catalog-id-or-key-or-slug>
pnpm hermes-fabric skills install <catalog-id-or-key-or-slug> [--as <slug>] [--force] --company-id <company-id>
```

Catalog semantics:

- **Bundled** skills live in `packages/skills-catalog/catalog/bundled/<category>/<slug>`
  and are recommended defaults for most companies. They use canonical key
  `hermes-fabric/bundled/<category>/<slug>`.
- **Optional** skills live in `packages/skills-catalog/catalog/optional/<category>/<slug>`
  and are role-specific or domain-specific (browser, AWS ops, etc.). Same key
  shape with `optional` in place of `bundled`.
- `skills install` materializes the catalog files into a company-managed skill
  directory and records provenance (`catalogId`, `catalogKey`, `packageVersion`,
  `originHash`, …) so future updates and audit decisions stay consistent.
- `--as <slug>` overrides the company skill slug. `--force` may replace a
  same-key catalog-managed skill but never bypasses hard validation or hard-stop
  audit findings.

Examples:

```sh
pnpm hermes-fabric skills browse --kind bundled --company-id <company-id>
pnpm hermes-fabric skills search "pull request" --kind bundled
pnpm hermes-fabric skills inspect github-pr-workflow
pnpm hermes-fabric skills install github-pr-workflow --company-id <company-id>
pnpm hermes-fabric skills install hermes-fabric:optional:browser:agent-browser --company-id <company-id>
```

External GitHub, skills.sh, local-path, and URL sources still go through
`skills import`; catalog commands are for the app-shipped catalog only.

### Company library

```sh
pnpm hermes-fabric skills list --company-id <company-id>
pnpm hermes-fabric skills show <skill-id-or-key-or-slug> --company-id <company-id>
pnpm hermes-fabric skills file <skill-id-or-key-or-slug> [--path SKILL.md] --company-id <company-id>
pnpm hermes-fabric skills import <source> --company-id <company-id>
pnpm hermes-fabric skills create --name "Review PRs" [--slug review-prs] [--description "..."] [--body-file SKILL.md] --company-id <company-id>
pnpm hermes-fabric skills scan-projects [--project-id <id>...] [--workspace-id <id>...] --company-id <company-id>
pnpm hermes-fabric skills check [skill-id-or-key-or-slug] --company-id <company-id>
pnpm hermes-fabric skills update <skill-id-or-key-or-slug> [--force] --company-id <company-id>
pnpm hermes-fabric skills update --all [--force] --company-id <company-id>
pnpm hermes-fabric skills audit [skill-id-or-key-or-slug] --company-id <company-id>
pnpm hermes-fabric skills reset <skill-id-or-key-or-slug> [--yes] [--force] --company-id <company-id>
pnpm hermes-fabric skills remove <skill-id-or-key-or-slug> --yes --company-id <company-id>
```

`skills import <source>` accepts a skills.sh URL, the equivalent
`<owner>/<repo>/<skill>` shorthand, a GitHub URL, a local path, or an
`npx skills add …` command. See `references/company-skills.md` in the agent
skill bundle for the source-type table.

`skills check`, `skills update`, `skills audit`, and `skills reset` are the
maintenance loop for catalog-installed skills:

- `check` reports whether each skill's installed bytes match its pinned origin
  (`hasUpdate`, `installedHash`, `originHash`, `updateHoldReason`,
  `auditVerdict`).
- `update` installs the pinned update through the existing install-update API.
  `--all` checks every company skill and updates only those with
  `hasUpdate=true`. `--force` discards local-modification or soft-audit holds;
  hard-stop audit findings still block the update.
- `audit` re-scans installed bytes and reports findings without executing
  anything.
- `reset` reinstalls a catalog-managed skill from its pinned origin, discarding
  local edits. Prompts in a TTY; requires `--yes` for non-interactive use.

### Agent attach

```sh
pnpm hermes-fabric skills agent list <agent-id-or-shortname> --company-id <company-id>
pnpm hermes-fabric skills agent sync <agent-id-or-shortname> --skill <skill-id-or-key-or-slug> [--skill <skill-id-or-key-or-slug>...] --company-id <company-id>
pnpm hermes-fabric skills agent clear <agent-id-or-shortname> --yes --company-id <company-id>
```

`skills agent sync` replaces the agent's non-required desired skill set (it is
not additive) and returns the resulting adapter `AgentSkillSnapshot`.
`skills agent clear` sends an empty desired list. Required Hermes Fabric skills are
still enforced by the server in both cases.

### Notes

- Skill references accept company skill `id`, canonical `key`, or unique
  `slug`; catalog references accept catalog `id`, `key`, or unique `slug`.
- `skills file` prints raw file content in human mode so it can be piped.
- `skills create --body-file -` reads the skill markdown body from stdin.
- `skills remove`, `skills reset`, and `skills agent clear` prompt in a TTY and
  require `--yes` in non-interactive use.
- `--json` prints the raw API result for each command.

## Teams Commands

`hermes-fabric teams` works with the app-shipped team catalog in
`@hermes-fabric/teams-catalog`. Browse, search, inspect, and file reads do not
change company state. `preview` runs the company import planner, and `install`
imports the catalog team into an existing company.

```sh
pnpm hermes-fabric teams browse [--kind bundled|optional] [--category <slug>] [--query <text>]
pnpm hermes-fabric teams search "<text>" [--kind bundled|optional] [--category <slug>]
pnpm hermes-fabric teams inspect <catalog-id-or-key-or-slug> [--file TEAM.md]
pnpm hermes-fabric teams preview <catalog-id-or-key-or-slug> --company-id <company-id>
pnpm hermes-fabric teams install <catalog-id-or-key-or-slug> --company-id <company-id>
```

Preview/install options:

- Under agent authentication, use `hermes-fabric company list --json`,
  `hermes-fabric company current --json`, or `HERMES_FABRIC_COMPANY_ID` to select the
  target company. `company list` falls back to the scoped current company when
  board-wide listing is forbidden. `teams install` creates agents and therefore
  requires board authentication, an `agents:create` grant, or an agent with
  explicit `canCreateAgents` permission.
- `--request-approval-on-forbidden` turns a 403 install denial into a linked
  board approval request instead of a raw failed command; use
  `--approval-issue-id <id>` to attach it to a specific issue. During Hermes Fabric
  task runs with `HERMES_FABRIC_TASK_ID` set, this fallback is automatic so
  agent-run walkthroughs leave a pending approval path instead of a raw 403.
- `--target-manager-agent-id <id>` or `--target-manager-slug <slug>` reparents
  catalog root agents under an existing manager.
- `--agent <slug>` and `--selected-file <path>` narrow the import.
- `--collision-strategy rename|skip|replace` controls name/key collisions.
- `--allow-external-sources`, `--allow-unpinned-optional-sources`, and
  `--allow-local-path-sources` explicitly opt into higher-trust source policy.
  Local-path sources are development-only and stay blocked unless that flag is
  passed.

## Secrets Commands

```sh
pnpm hermes-fabric secrets list --company-id <company-id>
pnpm hermes-fabric secrets declarations --company-id <company-id> [--include agents,projects] [--kind secret]
pnpm hermes-fabric secrets create --company-id <company-id> --name anthropic-api-key --value-env ANTHROPIC_API_KEY
pnpm hermes-fabric secrets link --company-id <company-id> --name prod-stripe-key --provider aws_secrets_manager --external-ref <provider-ref>
pnpm hermes-fabric secrets doctor --company-id <company-id>
pnpm hermes-fabric secrets provider-configs --company-id <company-id>
pnpm hermes-fabric secrets provider-config:create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric secrets provider-config:discovery-preview --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric secrets provider-config:get <config-id>
pnpm hermes-fabric secrets provider-config:update <config-id> --payload-json '{...}'
pnpm hermes-fabric secrets provider-config:default <config-id>
pnpm hermes-fabric secrets provider-config:health <config-id>
pnpm hermes-fabric secrets provider-config:delete <config-id>
pnpm hermes-fabric secrets remote-import:preview --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric secrets remote-import --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric secrets migrate-inline-env --company-id <company-id> [--apply]
```

Secret listing and declarations never print secret values. `create` accepts
`--value-env` so shell history does not capture the value. `link` records
provider-owned references without copying the secret value into Hermes Fabric.
For AWS-backed secrets, `secrets doctor` reports missing non-secret provider
env and the expected AWS SDK runtime credential source; do not store AWS
bootstrap credentials in Hermes Fabric secrets.

Per-company provider vaults (multiple vault instances per provider, default
vault selection, coming-soon GCP/Vault) can be configured from the board UI under
`Company Settings → Secrets → Provider vaults` or through the provider-config CLI
commands above. See the
[secrets deploy guide](../docs/deploy/secrets.md#provider-vaults) and
[API reference](../docs/api/secrets.md#provider-vaults) for the contract.

## Approval Commands

```sh
pnpm hermes-fabric approval list --company-id <company-id> [--status pending]
pnpm hermes-fabric approval get <approval-id>
pnpm hermes-fabric approval create --company-id <company-id> --type hire_agent --payload '{"name":"..."}' [--issue-ids <id1,id2>]
pnpm hermes-fabric approval approve <approval-id> [--decision-note "..."]
pnpm hermes-fabric approval reject <approval-id> [--decision-note "..."]
pnpm hermes-fabric approval request-revision <approval-id> [--decision-note "..."]
pnpm hermes-fabric approval resubmit <approval-id> [--payload '{"...":"..."}']
pnpm hermes-fabric approval comment <approval-id> --body "..."
```

## Activity Commands

```sh
pnpm hermes-fabric activity list --company-id <company-id> [--agent-id <agent-id>] [--entity-type issue] [--entity-id <id>]
pnpm hermes-fabric activity create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric activity issue <issue-id>
```

## Dashboard Commands

```sh
pnpm hermes-fabric dashboard get --company-id <company-id>
```

## Org And Agent Config Commands

```sh
pnpm hermes-fabric whoami
pnpm hermes-fabric openapi
pnpm hermes-fabric org get --company-id <company-id>
pnpm hermes-fabric org svg --company-id <company-id> [--out org.svg]
pnpm hermes-fabric org png --company-id <company-id> [--out org.png]
pnpm hermes-fabric agent-config list --company-id <company-id>
```

## Access, Profile, And Instance Commands

```sh
pnpm hermes-fabric profile session
pnpm hermes-fabric profile get
pnpm hermes-fabric profile update --payload-json '{...}'
pnpm hermes-fabric profile company-user <user-slug> --company-id <company-id>
pnpm hermes-fabric invite list --company-id <company-id>
pnpm hermes-fabric invite create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric invite revoke <invite-id>
pnpm hermes-fabric invite show <token>
pnpm hermes-fabric invite accept <token> [--payload-json '{...}']
pnpm hermes-fabric invite onboarding:text <token>
pnpm hermes-fabric join list --company-id <company-id> [--status pending_approval]
pnpm hermes-fabric join approve <request-id> --company-id <company-id>
pnpm hermes-fabric join reject <request-id> --company-id <company-id>
pnpm hermes-fabric join claim-key <request-id> --claim-secret <secret>
pnpm hermes-fabric member list --company-id <company-id>
pnpm hermes-fabric member update <member-id> --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric member role-and-grants <member-id> --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric member permissions <member-id> --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric member archive <member-id> --company-id <company-id> [--payload-json '{...}']
pnpm hermes-fabric admin user list [--query <text>]
pnpm hermes-fabric admin user promote <user-id>
pnpm hermes-fabric admin user demote <user-id>
pnpm hermes-fabric admin user company-access <user-id>
pnpm hermes-fabric admin user company-access:update <user-id> --payload-json '{...}'
```

CLI auth challenge endpoints are also exposed for tooling that needs the raw challenge lifecycle:

```sh
pnpm hermes-fabric auth challenge create --payload-json '{...}'
HERMES_FABRIC_CHALLENGE_SECRET=<challenge-secret> pnpm hermes-fabric auth challenge get <challenge-id> --token-env HERMES_FABRIC_CHALLENGE_SECRET
HERMES_FABRIC_CHALLENGE_SECRET=<challenge-secret> pnpm hermes-fabric auth challenge approve <challenge-id> --token-env HERMES_FABRIC_CHALLENGE_SECRET
HERMES_FABRIC_CHALLENGE_SECRET=<challenge-secret> pnpm hermes-fabric auth challenge cancel <challenge-id> --token-env HERMES_FABRIC_CHALLENGE_SECRET
pnpm hermes-fabric auth revoke-current
```

`--token <challenge-secret>` is still supported for compatibility, but `--token-env` avoids putting challenge secrets in shell history or process arguments.

## Instance Settings Commands

```sh
pnpm hermes-fabric instance scheduler-heartbeats
pnpm hermes-fabric instance settings:general
pnpm hermes-fabric instance settings:general:update --payload-json '{...}'
pnpm hermes-fabric instance settings:experimental
pnpm hermes-fabric instance settings:experimental:update --payload-json '{...}'
pnpm hermes-fabric instance database-backup
```

Experimental features are opt-in and are provided without compatibility guarantees. They may break, change, or be removed at any time. Use them at your own risk.

```sh
pnpm hermes-fabric sidebar preferences
pnpm hermes-fabric sidebar preferences:update --payload-json '{...}'
pnpm hermes-fabric sidebar project-preferences --company-id <company-id>
pnpm hermes-fabric sidebar project-preferences:update --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric sidebar badges --company-id <company-id>
pnpm hermes-fabric inbox dismissals --company-id <company-id>
pnpm hermes-fabric inbox dismiss --company-id <company-id> --payload-json '{"itemKey":"run:<run-id>"}'
pnpm hermes-fabric board-claim show <token>
pnpm hermes-fabric board-claim claim <token> [--payload-json '{...}']
pnpm hermes-fabric openclaw invite-prompt --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric available-skill list
pnpm hermes-fabric available-skill index
pnpm hermes-fabric available-skill get <skill-name>
pnpm hermes-fabric llm agent-configuration
pnpm hermes-fabric llm agent-configuration:adapter <adapter-type>
pnpm hermes-fabric llm agent-icons
```

Hermes gateway uses the generic invite/join commands above rather than
`openclaw invite-prompt`. Create an agent invite, read
`invite onboarding:text`, submit a join request with
`adapterType: "hermes_gateway"` and `agentDefaultsPayload.apiBaseUrl` /
`agentDefaultsPayload.apiKey`, then approve and claim the key with the `join`
commands. See [HERMES_GATEWAY_ONBOARDING.md](./HERMES_GATEWAY_ONBOARDING.md).

## Adapter, Asset, And Skill Commands

```sh
pnpm hermes-fabric adapter list
pnpm hermes-fabric adapter install --payload-json '{"packageName":"@scope/adapter","version":"1.2.3"}'
pnpm hermes-fabric adapter get <adapter-type>
pnpm hermes-fabric adapter update <adapter-type> --payload-json '{"disabled":true}'
pnpm hermes-fabric adapter override <adapter-type> --payload-json '{"paused":true}'
pnpm hermes-fabric adapter reload <adapter-type>
pnpm hermes-fabric adapter reinstall <adapter-type>
pnpm hermes-fabric adapter delete <adapter-type>
pnpm hermes-fabric adapter config-schema <adapter-type>
pnpm hermes-fabric adapter ui-parser <adapter-type>
pnpm hermes-fabric adapter models <adapter-type> --company-id <company-id> [--refresh] [--environment-id <id>]
pnpm hermes-fabric adapter model-profiles <adapter-type> --company-id <company-id>
pnpm hermes-fabric adapter detect-model <adapter-type> --company-id <company-id>
pnpm hermes-fabric adapter test-environment <adapter-type> --company-id <company-id> --payload-json '{...}'
```

```sh
pnpm hermes-fabric asset image:upload --company-id <company-id> --file ./image.png [--namespace docs] [--alt "..."]
pnpm hermes-fabric asset logo:upload --company-id <company-id> --file ./logo.svg
pnpm hermes-fabric asset content <asset-id> --out ./asset.bin
```

```sh
pnpm hermes-fabric skill list --company-id <company-id>
pnpm hermes-fabric skill get <skill-id> --company-id <company-id>
pnpm hermes-fabric skill file <skill-id> --company-id <company-id> [--path SKILL.md]
pnpm hermes-fabric skill create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric skill file:update <skill-id> --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric skill import --company-id <company-id> --payload-json '{"source":"github:owner/repo/path"}'
pnpm hermes-fabric skill scan-projects --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric skill update-status <skill-id> --company-id <company-id>
pnpm hermes-fabric skill install-update <skill-id> --company-id <company-id>
pnpm hermes-fabric skill delete <skill-id> --company-id <company-id>
```

## Cost, Finance, And Budget Commands

```sh
pnpm hermes-fabric cost summary --company-id <company-id>
pnpm hermes-fabric cost by-agent --company-id <company-id>
pnpm hermes-fabric cost by-agent-model --company-id <company-id>
pnpm hermes-fabric cost by-provider --company-id <company-id>
pnpm hermes-fabric cost by-biller --company-id <company-id>
pnpm hermes-fabric cost by-project --company-id <company-id>
pnpm hermes-fabric cost window-spend --company-id <company-id>
pnpm hermes-fabric cost quota-windows --company-id <company-id>
pnpm hermes-fabric cost issue <issue-id>
pnpm hermes-fabric cost event:create --company-id <company-id> --payload-json '{...}'
```

```sh
pnpm hermes-fabric finance event:create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric finance events --company-id <company-id>
pnpm hermes-fabric finance summary --company-id <company-id>
pnpm hermes-fabric finance by-biller --company-id <company-id>
pnpm hermes-fabric finance by-kind --company-id <company-id>
pnpm hermes-fabric budget overview --company-id <company-id>
pnpm hermes-fabric budget policy:upsert --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric budget company:update --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric budget agent:update <agent-id> --payload-json '{...}'
pnpm hermes-fabric budget incident:resolve <incident-id> --company-id <company-id> [--payload-json '{...}']
```

## Workspace And Environment Commands

```sh
pnpm hermes-fabric workspace list --company-id <company-id>
pnpm hermes-fabric workspace get <execution-workspace-id>
pnpm hermes-fabric workspace close-readiness <execution-workspace-id>
pnpm hermes-fabric workspace operations <execution-workspace-id>
pnpm hermes-fabric workspace update <execution-workspace-id> --payload-json '{...}'
pnpm hermes-fabric workspace runtime-service <execution-workspace-id> start --payload-json '{...}'
pnpm hermes-fabric workspace runtime-command <execution-workspace-id> run --payload-json '{...}'
```

```sh
pnpm hermes-fabric environment list --company-id <company-id>
pnpm hermes-fabric environment capabilities --company-id <company-id>
pnpm hermes-fabric environment create --company-id <company-id> --payload-json '{...}'
pnpm hermes-fabric environment get <environment-id>
pnpm hermes-fabric environment leases <environment-id>
pnpm hermes-fabric environment lease <lease-id>
pnpm hermes-fabric environment update <environment-id> --payload-json '{...}'
pnpm hermes-fabric environment delete <environment-id>
pnpm hermes-fabric environment probe <environment-id>
pnpm hermes-fabric environment probe-config --company-id <company-id> --payload-json '{...}'
```

```sh
pnpm hermes-fabric project-workspace list <project-id>
pnpm hermes-fabric project-workspace create <project-id> --payload-json '{...}'
pnpm hermes-fabric project-workspace update <project-id> <workspace-id> --payload-json '{...}'
pnpm hermes-fabric project-workspace delete <project-id> <workspace-id>
pnpm hermes-fabric project-workspace runtime-service <project-id> <workspace-id> restart --payload-json '{...}'
pnpm hermes-fabric project-workspace runtime-command <project-id> <workspace-id> run --payload-json '{...}'
```

## Plugin Commands

Existing plugin lifecycle commands remain available: `plugin init`, `list`, `install`, `uninstall`, `enable`, `disable`, `inspect`, and `examples`.

```sh
pnpm hermes-fabric plugin ui-contributions
pnpm hermes-fabric plugin tools
pnpm hermes-fabric plugin tool:execute --payload-json '{...}'
pnpm hermes-fabric plugin health <plugin-id>
pnpm hermes-fabric plugin logs <plugin-id>
pnpm hermes-fabric plugin upgrade <plugin-id>
pnpm hermes-fabric plugin config <plugin-id>
pnpm hermes-fabric plugin config:set <plugin-id> --payload-json '{"configJson":{...}}'
pnpm hermes-fabric plugin config:test <plugin-id> --payload-json '{"configJson":{...}}'
pnpm hermes-fabric plugin jobs <plugin-id>
pnpm hermes-fabric plugin job:runs <plugin-id> <job-id>
pnpm hermes-fabric plugin job:trigger <plugin-id> <job-id> [--payload-json '{...}']
pnpm hermes-fabric plugin webhook <plugin-id> <endpoint-key> [--payload-json '{...}']
pnpm hermes-fabric plugin dashboard <plugin-id>
pnpm hermes-fabric plugin bridge:data <plugin-id> --payload-json '{...}'
pnpm hermes-fabric plugin bridge:action <plugin-id> --payload-json '{...}'
pnpm hermes-fabric plugin bridge:stream <plugin-id> <channel> [--duration-ms 10000]
pnpm hermes-fabric plugin data <plugin-id> <key> --payload-json '{...}'
pnpm hermes-fabric plugin action <plugin-id> <key> --payload-json '{...}'
pnpm hermes-fabric plugin local-folders <plugin-id> --company-id <company-id>
pnpm hermes-fabric plugin local-folder:status <plugin-id> <folder-key> --company-id <company-id>
pnpm hermes-fabric plugin local-folder:validate <plugin-id> <folder-key> --company-id <company-id> [--payload-json '{...}']
pnpm hermes-fabric plugin local-folder:set <plugin-id> <folder-key> --company-id <company-id> --payload-json '{...}'
```

Feedback traces can be fetched directly by ID when automating export workflows:

```sh
pnpm hermes-fabric feedback trace <trace-id>
pnpm hermes-fabric feedback bundle <trace-id>
```

## Heartbeat Command

`heartbeat run` now also supports context/api-key options and uses the shared client stack:

```sh
pnpm hermes-fabric heartbeat run --agent-id <agent-id> [--api-base http://localhost:3100] [--api-key <token>]
```

## Local Storage Defaults

Local Hermes Fabric data lives under the selected instance root. `HERMES_FABRIC_HOME` chooses the home directory and `HERMES_FABRIC_INSTANCE_ID` chooses the instance.

```text
~/.hermes-fabric/                                     # HERMES_FABRIC_HOME
└── instances/
    └── default/                                  # instance root (HERMES_FABRIC_INSTANCE_ID)
        ├── config.json                           # runtime config
        ├── .env                                  # instance env file
        ├── db/                                   # embedded PostgreSQL data
        ├── data/
        │   ├── storage/                          # local_disk uploads
        │   └── backups/                          # automatic DB backups
        ├── logs/
        ├── secrets/
        │   └── master.key                        # local_encrypted master key
        ├── workspaces/                           # default agent workspaces
        ├── projects/                             # project execution workspaces
        ├── companies/                            # per-company adapter homes (e.g. codex-home)
        └── codex-home/                           # per-instance codex home (when not company-scoped)
```

Default paths for the canonical install:

- config: `~/.hermes-fabric/instances/default/config.json`
- embedded db: `~/.hermes-fabric/instances/default/db`
- logs: `~/.hermes-fabric/instances/default/logs`
- storage: `~/.hermes-fabric/instances/default/data/storage`
- secrets key: `~/.hermes-fabric/instances/default/secrets/master.key`

Override base home or instance with env vars:

```sh
HERMES_FABRIC_HOME=/custom/home HERMES_FABRIC_INSTANCE_ID=dev pnpm hermes-fabric run
```

## Storage Configuration

Configure storage provider and settings:

```sh
pnpm hermes-fabric configure --section storage
```

Supported providers:

- `local_disk` (default; local single-user installs)
- `s3` (S3-compatible object storage)
