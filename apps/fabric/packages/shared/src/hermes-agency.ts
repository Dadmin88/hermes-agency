export type HermesAgencyAgentStatus = "online" | "offline" | "sleeping" | "disabled" | "wake_failed";

export interface HermesAgencyAgent {
  name: string;
  department: string | null;
  description: string;
  skills: string[];
  online: boolean;
  disabled: boolean;
  status: HermesAgencyAgentStatus;
  lastSeen: string | null;
  peerId: string | null;
  peerIdRedacted: boolean;
  wakeAttempts: number;
  lastAttempt: string | null;
  lastError: string | null;
  model: string | null;
  provider: string | null;
}

export interface HermesAgencyRosterResponse {
  tenant: string;
  filter: string;
  total: number;
  online: number;
  offline: number;
  disabled: number;
  agents: HermesAgencyAgent[];
}

export type HermesKanbanProjectionSyncStatus = "ok" | "unavailable" | "error";

export interface HermesKanbanProjectionStatus {
  enabled: boolean;
  dbPath: string | null;
  companyId: string | null;
  lastSyncAt: string | null;
  lastStatus: HermesKanbanProjectionSyncStatus | "disabled";
  projectedCount: number;
  syncedCount: number;
  lastError: string | null;
}

export type HermesAgencyTaskPacketDispatchMode = "direct-agent" | "skill-fit";

export interface HermesAgencyTaskPacketIssueLike {
  id?: string | null;
  identifier?: string | null;
  title: string;
  description?: string | null;
  status?: string | null;
  priority?: string | null;
  workMode?: string | null;
  labels?: Array<string | { name?: string | null } | null> | null;
  project?: { name?: string | null; description?: string | null } | null;
  goal?: { title?: string | null; description?: string | null } | null;
  currentExecutionWorkspace?: {
    id?: string | null;
    name?: string | null;
    rootPath?: string | null;
    path?: string | null;
    branchName?: string | null;
    gitBranch?: string | null;
  } | null;
}

export interface HermesAgencyTaskPacketPreviewInput {
  issue: HermesAgencyTaskPacketIssueLike;
  requestedSkills?: readonly string[];
  targetAgentName?: string | null;
  validationExpectations?: readonly string[];
  artifactExpectations?: readonly string[];
  stopConditions?: readonly string[];
}

export interface HermesAgencyTaskPacketPreview {
  title: string;
  goal: string;
  context: string;
  requestedSkills: string[];
  targetAgentName: string | null;
  dispatchMode: HermesAgencyTaskPacketDispatchMode;
  routing: {
    mode: HermesAgencyTaskPacketDispatchMode;
    rationale: string;
  };
  workspaceContext: {
    issueId: string | null;
    issueIdentifier: string | null;
    projectName: string | null;
    goalTitle: string | null;
    workspaceId: string | null;
    workspaceName: string | null;
    workspaceRoot: string | null;
    branchName: string | null;
  };
  validationExpectations: string[];
  artifactExpectations: string[];
  stopConditions: string[];
  dispatchReady: false;
}

export type HermesAgencyDispatchMode = "skill-fit" | "direct-agent";
export type HermesAgencyDispatchStatus = "queued" | "wake_attempted" | "wake_failed" | "running" | "blocked" | "completed" | "failed";

export interface HermesAgencyDispatchArtifact {
  type: string;
  text?: string;
  path?: string;
  url?: string;
  metadata?: Record<string, unknown>;
}

export interface HermesAgencyDispatchStatusTransition {
  status: HermesAgencyDispatchStatus;
  at: string;
  message: string | null;
}

export interface HermesAgencyDispatchRecord {
  id: string;
  createdAt: string;
  updatedAt: string;
  packet: HermesAgencyTaskPacketPreview;
  mode: HermesAgencyDispatchMode;
  skill: string | null;
  targetAgentName: string | null;
  taskId: string | null;
  queueId: string | null;
  status: HermesAgencyDispatchStatus;
  message: string | null;
  artifacts: HermesAgencyDispatchArtifact[];
  statusHistory: HermesAgencyDispatchStatusTransition[];
  raw: unknown;
}

const DEFAULT_VALIDATION_EXPECTATIONS = [
  "Run the smallest relevant automated check before reporting completion.",
  "Report the exact checks run and whether they passed, failed, or were blocked.",
];

const DEFAULT_ARTIFACT_EXPECTATIONS = [
  "Return a concise report with files changed, checks run, risks, and recommended next step.",
];

const DEFAULT_STOP_CONDITIONS = [
  "Stop before dispatching to Hermes Agency; this packet is preview-only.",
  "Stop and report if the requested work would require secrets, credentials, or destructive system changes.",
];

function cleanString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function normalizeList(values: readonly string[] | undefined, fallback: readonly string[]): string[] {
  const source = values && values.length > 0 ? values : fallback;
  return source.map((value) => value.trim()).filter((value) => value.length > 0);
}

function labelName(label: string | { name?: string | null } | null): string | null {
  if (typeof label === "string") return cleanString(label);
  return cleanString(label?.name);
}

function normalizeSkills(issue: HermesAgencyTaskPacketIssueLike, requestedSkills: readonly string[] | undefined): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  const push = (value: string | null) => {
    if (!value) return;
    const skill = value.toLowerCase().replace(/\s+/g, "-");
    if (skill.length === 0 || seen.has(skill)) return;
    seen.add(skill);
    result.push(skill);
  };

  for (const skill of requestedSkills ?? []) push(cleanString(skill));
  for (const label of issue.labels ?? []) push(labelName(label));
  return result;
}

function buildTitle(issue: HermesAgencyTaskPacketIssueLike): string {
  const title = cleanString(issue.title) ?? "Untitled Hermes Fabric task";
  const identifier = cleanString(issue.identifier);
  return identifier ? `[${identifier}] ${title}` : title;
}

function buildGoal(issue: HermesAgencyTaskPacketIssueLike): string {
  return cleanString(issue.description) ?? cleanString(issue.title) ?? "Complete the Hermes Fabric task.";
}

function buildContext(input: {
  issue: HermesAgencyTaskPacketIssueLike;
  workspaceContext: HermesAgencyTaskPacketPreview["workspaceContext"];
  validationExpectations: string[];
  artifactExpectations: string[];
  stopConditions: string[];
}): string {
  const { issue, workspaceContext, validationExpectations, artifactExpectations, stopConditions } = input;
  const lines = [
    "Hermes Fabric task packet preview (read-only; do not dispatch).",
    `Issue: ${buildTitle(issue)}`,
    `Status: ${cleanString(issue.status) ?? "unknown"}`,
    `Priority: ${cleanString(issue.priority) ?? "unknown"}`,
    `Work mode: ${cleanString(issue.workMode) ?? "unknown"}`,
  ];

  if (workspaceContext.projectName) lines.push(`Project: ${workspaceContext.projectName}`);
  if (issue.project?.description) lines.push(`Project description: ${issue.project.description}`);
  if (workspaceContext.goalTitle) lines.push(`Goal: ${workspaceContext.goalTitle}`);
  if (workspaceContext.workspaceName) lines.push(`Workspace: ${workspaceContext.workspaceName}`);
  if (workspaceContext.workspaceRoot) lines.push(`Workspace root: ${workspaceContext.workspaceRoot}`);
  if (workspaceContext.branchName) lines.push(`Branch: ${workspaceContext.branchName}`);
  const description = cleanString(issue.description);
  if (description) lines.push("", "Task description:", description);

  lines.push("", "Validation expectations:", ...validationExpectations.map((item) => `- ${item}`));
  lines.push("", "Artifact expectations:", ...artifactExpectations.map((item) => `- ${item}`));
  lines.push("", "Stop conditions:", ...stopConditions.map((item) => `- ${item}`));
  return lines.join("\n");
}

export function buildHermesAgencyTaskPacketPreview(
  input: HermesAgencyTaskPacketPreviewInput,
): HermesAgencyTaskPacketPreview {
  const targetAgentName = cleanString(input.targetAgentName);
  const dispatchMode: HermesAgencyTaskPacketDispatchMode = targetAgentName ? "direct-agent" : "skill-fit";
  const validationExpectations = normalizeList(input.validationExpectations, DEFAULT_VALIDATION_EXPECTATIONS);
  const artifactExpectations = normalizeList(input.artifactExpectations, DEFAULT_ARTIFACT_EXPECTATIONS);
  const stopConditions = normalizeList(input.stopConditions, DEFAULT_STOP_CONDITIONS);
  const workspace = input.issue.currentExecutionWorkspace ?? null;
  const workspaceContext: HermesAgencyTaskPacketPreview["workspaceContext"] = {
    issueId: cleanString(input.issue.id),
    issueIdentifier: cleanString(input.issue.identifier),
    projectName: cleanString(input.issue.project?.name),
    goalTitle: cleanString(input.issue.goal?.title),
    workspaceId: cleanString(workspace?.id),
    workspaceName: cleanString(workspace?.name),
    workspaceRoot: cleanString(workspace?.rootPath) ?? cleanString(workspace?.path),
    branchName: cleanString(workspace?.branchName) ?? cleanString(workspace?.gitBranch),
  };
  const requestedSkills = normalizeSkills(input.issue, input.requestedSkills);

  return {
    title: buildTitle(input.issue),
    goal: buildGoal(input.issue),
    context: buildContext({
      issue: input.issue,
      workspaceContext,
      validationExpectations,
      artifactExpectations,
      stopConditions,
    }),
    requestedSkills,
    targetAgentName,
    dispatchMode,
    routing: {
      mode: dispatchMode,
      rationale: targetAgentName
        ? `Direct agent target selected: ${targetAgentName}.`
        : "Skill-fit routing will choose the best Hermes Agency specialist from requestedSkills.",
    },
    workspaceContext,
    validationExpectations,
    artifactExpectations,
    stopConditions,
    dispatchReady: false,
  };
}
