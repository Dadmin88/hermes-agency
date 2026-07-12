/**
 * Hermes Agent adapter for HermesFabric.
 *
 * Runs Hermes Agent (https://github.com/NousResearch/hermes-agent)
 * as a managed employee in a HermesFabric company. Hermes Agent is a
 * full-featured AI agent with 30+ native tools, persistent memory,
 * skills, session persistence, and MCP support.
 *
 * @packageDocumentation
 */

import type {
  AdapterRuntimeCommandSpec,
  AdapterSessionManagement,
  ServerAdapterModule,
} from "@hermes-fabric/adapter-utils";

import { ADAPTER_TYPE, ADAPTER_LABEL } from "./shared/constants.js";
import {
  execute,
  testEnvironment,
  sessionCodec,
  listSkills,
  syncSkills,
  detectModel,
  getConfigSchema,
} from "./server/index.js";
import { resolveHermesCommand } from "./server/execute.js";

export const type = ADAPTER_TYPE;
export const label = ADAPTER_LABEL;
export {
  createServerAdapter as createHermesGatewayServerAdapter,
  agentConfigurationDoc as hermesGatewayAgentConfigurationDoc,
  label as hermesGatewayLabel,
  models as hermesGatewayModels,
  type as hermesGatewayType,
} from "./gateway/index.js";

/**
 * Models available through Hermes Agent.
 *
 * Hermes supports any model via any provider. The HermesFabric UI should
 * prefer detectModel() plus manual entry over curated placeholder models,
 * since Hermes availability depends on the user's local configuration.
 */
export const models: { id: string; label: string }[] = [];

const sessionManagement: AdapterSessionManagement = {
  supportsSessionResume: true,
  nativeContextManagement: "confirmed",
  defaultSessionCompaction: {
    enabled: true,
    maxSessionRuns: 0,
    maxRawInputTokens: 0,
    maxSessionAgeHours: 0,
  },
};

function getRuntimeCommandSpec(config: Record<string, unknown>): AdapterRuntimeCommandSpec {
  const command = resolveHermesCommand(config);
  return {
    command,
    detectCommand: command,
    installCommand: null,
  };
}

/**
 * Documentation shown in the HermesFabric UI when configuring a Hermes agent.
 */
export const agentConfigurationDoc = `# Hermes Agent Configuration

Hermes Agent is a full-featured AI agent by Nous Research with 30+ native
tools, persistent memory, session persistence, skills, and MCP support.

## Prerequisites

- Python 3.10+ installed
- Hermes Agent installed: \`pip install hermes-agent\`
- At least one LLM API key configured in ~/.hermes/.env

## Core Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| model | string | (Hermes configured default) | Optional explicit model in provider/model format. Leave blank to use Hermes's configured default model. |
| provider | string | (auto) | API provider: auto, openrouter, nous, openai-codex, zai, kimi-coding, minimax, minimax-cn. Usually not needed — Hermes auto-detects from model name. |
| timeoutSec | number | 300 | Execution timeout in seconds |
| graceSec | number | 10 | Grace period after SIGTERM before SIGKILL |

## Tool Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| toolsets | string | (all) | Comma-separated toolsets to enable (e.g. "terminal,file,web") |

## Session & Workspace

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| persistSession | boolean | true | Resume sessions across heartbeats |
| worktreeMode | boolean | false | Use git worktree for isolated changes |
| checkpoints | boolean | false | Enable filesystem checkpoints |

## Advanced

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| hermesCommand | string | hermes | Path to hermes CLI binary |
| verbose | boolean | false | Enable verbose output |
| extraArgs | string[] | [] | Additional CLI arguments |
| env | object | {} | Extra environment variables |
| promptTemplate | string | (default) | Custom prompt template with {{variable}} placeholders |

## Hermes-Originated HermesFabric Tasks

This adapter package also ships a Hermes-facing HermesFabric task bridge skill:
\`fabric-task-bridge\`. Use it when a user starts in Hermes and asks Hermes
to create, comment on, update, or list HermesFabric tasks.

Configure credentials through Hermes env/profile secrets, never in prompt text:

- \`HERMES_FABRIC_API_URL\` - HermesFabric base URL, with or without \`/api\`
- \`HERMES_FABRIC_BRIDGE_API_KEY\` - HermesFabric agent API key created with \`scope.kind = "task_bridge"\`
- optional fallback \`HERMES_FABRIC_API_KEY\` - must still be a task_bridge key, never a normal claimed agent key
- optional \`HERMES_FABRIC_COMPANY_ID\`, \`HERMES_FABRIC_AGENT_ID\`, and \`HERMES_FABRIC_RUN_ID\`

The bridge is separate from adapter execution:

- \`hermes_local\` means HermesFabric shells out to local \`hermes chat\`.
- \`hermes_gateway\` means HermesFabric wakes remote Hermes through Hermes's API server.
- \`fabric-task-bridge\` means Hermes calls HermesFabric's REST API to manage tasks.

Create task bridge keys with a parent issue or project boundary. Do not expose
normal claimed HermesFabric agent API keys to internet-facing Hermes chat/webhook
task-bridge surfaces.

## Available Template Variables

- \`{{agentId}}\` — HermesFabric agent ID
- \`{{agentName}}\` — Agent display name
- \`{{companyId}}\` — HermesFabric company ID
- \`{{companyName}}\` — Company display name
- \`{{runId}}\` — Current heartbeat run ID
- \`{{taskId}}\` — Current task/issue ID (if assigned)
- \`{{taskTitle}}\` — Task title (if assigned)
- \`{{taskBody}}\` — Task description (if assigned)
- \`{{projectName}}\` — Project name (if scoped to a project)
`;

/**
 * External adapter plugin entrypoint expected by HermesFabric's adapter manager.
 */
export function createServerAdapter(): ServerAdapterModule {
  return {
    type,
    execute,
    testEnvironment,
    sessionCodec,
    sessionManagement,
    listSkills,
    syncSkills,
    models,
    supportsLocalAgentJwt: true,
    supportsInstructionsBundle: true,
    instructionsPathKey: "instructionsFilePath",
    requiresMaterializedRuntimeSkills: false,
    getRuntimeCommandSpec,
    agentConfigurationDoc,
    detectModel,
    getConfigSchema,
  };
}

export { createServerAdapter as createHermesLocalServerAdapter };
