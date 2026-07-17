import { execFile } from "node:child_process";
import { realpathSync } from "node:fs";
import { promisify } from "node:util";
import { and, eq, inArray } from "drizzle-orm";
import type { Db } from "@hermes-fabric/db";
import { agents, authUsers, companyMemberships, issues, projects } from "@hermes-fabric/db";
import { logger } from "../middleware/logger.js";
import {
  HERMES_KANBAN_TASK_ORIGIN_KIND,
  resolveHermesKanbanBoard,
  resolveHermesKanbanCompanyId,
  resolveHermesKanbanDbPath,
} from "./hermes-kanban-issues.js";

export { resolveHermesKanbanBoard } from "./hermes-kanban-issues.js";

const execFileAsync = promisify(execFile);
const REVERSE_SYNC_FIELDS = [
  "assigneeAgentId",
  "projectId",
  "labels",
  "reviewers",
  "approvers",
  "executionPolicy",
] as const;
const SYNC_LABEL_NAMESPACE = /^(?:hermes|risk|skill|routing):/i;
const HIGH_RISK_POLICY_TERM = /(?:deploy|destructive|security|secrets?|production)/i;

type ReverseSyncField = (typeof REVERSE_SYNC_FIELDS)[number];
type IssueSnapshot = Pick<
  typeof issues.$inferSelect,
  | "id"
  | "companyId"
  | "originKind"
  | "originId"
  | "originFingerprint"
  | "status"
  | "assigneeAgentId"
  | "projectId"
  | "executionPolicy"
  | "executionState"
> & {
  labels?: Array<{ id: string; name: string }>;
};

type ReverseSyncCommand = {
  taskId: string;
  patch: Record<string, unknown>;
  actor: string;
  expectedOriginFingerprint: string;
  board: string | null;
  dbPath: string | null;
};

export type HermesKanbanReverseSyncResult = {
  attempted: boolean;
  accepted: boolean;
  pending: boolean;
  warning: string | null;
  fields: ReverseSyncField[];
};

type CommandRunner = (command: ReverseSyncCommand) => Promise<Record<string, unknown>>;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function nameKey(agent: { name: string; metadata: Record<string, unknown> | null }) {
  const metadataNameKey = asRecord(agent.metadata)?.name_key;
  return typeof metadataNameKey === "string" && metadataNameKey.trim()
    ? metadataNameKey.trim()
    : agent.name;
}

async function defaultCommandRunner(command: ReverseSyncCommand) {
  const executable = process.env.FABRIC_HERMES_CLI?.trim() || "hermes";
  const args = [
    "agency",
    "fabric-metadata-sync",
    command.taskId,
    "--patch-json",
    JSON.stringify(command.patch),
    "--actor",
    command.actor,
    "--fingerprint",
    command.expectedOriginFingerprint,
  ];
  if (command.board) args.push("--board", command.board);
  if (command.dbPath) args.push("--db", command.dbPath);
  const { stdout } = await execFileAsync(executable, args, {
    timeout: 15_000,
    maxBuffer: 256_000,
    env: command.dbPath
      ? { ...process.env, HERMES_KANBAN_DB: command.dbPath }
      : process.env,
  });
  return JSON.parse(stdout) as Record<string, unknown>;
}

function projectionState(value: unknown) {
  const current = asRecord(value) ?? {};
  const projection = asRecord(current.hermesKanbanProjection) ?? {};
  return { current, projection };
}

function projectionSource(value: unknown) {
  return asRecord(projectionState(value).projection.source);
}

function mergeReverseSyncState(
  executionState: unknown,
  input: {
    fields: ReverseSyncField[];
    status: "accepted" | "pending" | "failed";
    warning: string | null;
  },
) {
  const { current, projection } = projectionState(executionState);
  const warnings = Array.isArray(projection.warnings)
    ? projection.warnings.filter((value): value is string => typeof value === "string")
    : [];
  const nextWarnings = input.warning ? [...new Set([...warnings, input.warning])] : warnings;
  const managedFields = { ...(asRecord(projection.managedFields) ?? {}) };
  for (const field of input.fields) {
    const previousManagement = asRecord(managedFields[field]) ?? {};
    managedFields[field] = {
      ...previousManagement,
      owner: input.status === "accepted" ? "fabric_manual_override" : "fabric_pending_reverse_sync",
      lastSyncedAt: input.status === "accepted" ? new Date().toISOString() : null,
      reverseSyncStatus: input.status,
    };
  }
  return {
    ...current,
    hermesKanbanProjection: {
      ...projection,
      managedFields,
      warnings: nextWarnings,
      pendingReverseSync: input.status === "pending" ? input.fields : [],
      reverseSyncFailed: input.status === "failed" ? input.warning : null,
    },
  };
}

function syncedLabelNames(issue: IssueSnapshot) {
  return (issue.labels ?? [])
    .map((label) => label.name.trim().toLowerCase())
    .filter((name) => SYNC_LABEL_NAMESPACE.test(name))
    .sort();
}

function policyParticipantKeys(policy: unknown, type: "review" | "approval") {
  const stages = asRecord(policy)?.stages;
  if (!Array.isArray(stages)) return [];
  const values: string[] = [];
  for (const rawStage of stages) {
    const stage = asRecord(rawStage);
    if (stage?.type !== type || !Array.isArray(stage.participants)) continue;
    for (const rawParticipant of stage.participants) {
      const participant = asRecord(rawParticipant);
      if (participant?.type === "agent" && typeof participant.agentId === "string") {
        values.push(`agent:${participant.agentId}`);
      } else if (participant?.type === "user" && typeof participant.userId === "string") {
        values.push(`user:${participant.userId}`);
      }
    }
  }
  return [...new Set(values)].sort();
}

function changedFields(previous: IssueSnapshot, next: IssueSnapshot): ReverseSyncField[] {
  const fields: ReverseSyncField[] = [];
  for (const field of ["assigneeAgentId", "projectId"] as const) {
    if (JSON.stringify(previous[field] ?? null) !== JSON.stringify(next[field] ?? null)) fields.push(field);
  }
  if (JSON.stringify(syncedLabelNames(previous)) !== JSON.stringify(syncedLabelNames(next))) fields.push("labels");
  if (JSON.stringify(policyParticipantKeys(previous.executionPolicy, "review"))
    !== JSON.stringify(policyParticipantKeys(next.executionPolicy, "review"))) fields.push("reviewers");
  if (JSON.stringify(policyParticipantKeys(previous.executionPolicy, "approval"))
    !== JSON.stringify(policyParticipantKeys(next.executionPolicy, "approval"))) fields.push("approvers");
  if (JSON.stringify(previous.executionPolicy ?? null) !== JSON.stringify(next.executionPolicy ?? null)) {
    fields.push("executionPolicy");
  }
  return fields;
}

function collectHighRiskPolicyFacts(value: unknown, path = "", facts = new Set<string>()) {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => collectHighRiskPolicyFacts(entry, `${path}[${index}]`, facts));
  } else if (value && typeof value === "object") {
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      const nextPath = path ? `${path}.${key}` : key;
      if (HIGH_RISK_POLICY_TERM.test(key) && entry !== false && entry !== null) {
        facts.add(`${nextPath}:${JSON.stringify(entry)}`);
      }
      collectHighRiskPolicyFacts(entry, nextPath, facts);
    }
  } else if (typeof value === "string" && HIGH_RISK_POLICY_TERM.test(value)) {
    facts.add(`${path}:${value.toLowerCase()}`);
  }
  return facts;
}

function isPolicyLoosening(previous: unknown, next: unknown) {
  const before = asRecord(previous);
  const after = asRecord(next);
  if (!before || !after) return Boolean(before && !after);
  const afterReviewers = new Set(policyParticipantKeys(after, "review"));
  const afterApprovers = new Set(policyParticipantKeys(after, "approval"));
  if (policyParticipantKeys(before, "review").some((value) => !afterReviewers.has(value))) return true;
  if (policyParticipantKeys(before, "approval").some((value) => !afterApprovers.has(value))) return true;
  const afterFacts = collectHighRiskPolicyFacts(after);
  return [...collectHighRiskPolicyFacts(before)].some((fact) => !afterFacts.has(fact));
}

async function governanceValues(db: Db, issue: IssueSnapshot, type: "review" | "approval") {
  const keys = policyParticipantKeys(issue.executionPolicy, type);
  const agentIds = keys.filter((key) => key.startsWith("agent:")).map((key) => key.slice(6));
  const userIds = keys.filter((key) => key.startsWith("user:")).map((key) => key.slice(5));
  const agentRows = agentIds.length > 0
    ? await db.select({ id: agents.id, name: agents.name, metadata: agents.metadata })
      .from(agents)
      .where(and(eq(agents.companyId, issue.companyId), inArray(agents.id, agentIds)))
    : [];
  const userRows = userIds.length > 0
    ? await db.select({ id: authUsers.id })
      .from(companyMemberships)
      .innerJoin(authUsers, eq(authUsers.id, companyMemberships.principalId))
      .where(and(
        eq(companyMemberships.companyId, issue.companyId),
        eq(companyMemberships.principalType, "user"),
        eq(companyMemberships.status, "active"),
        inArray(companyMemberships.principalId, userIds),
      ))
    : [];
  const agentsById = new Map(agentRows.map((row) => [row.id, row]));
  const companyUserIds = new Set(userRows.map((row) => row.id));
  return keys.map((key) => {
    if (key.startsWith("agent:")) {
      const id = key.slice(6);
      const agent = agentsById.get(id);
      if (!agent) throw new Error(`reverse sync ${type} participant is not a company-scoped agent`);
      return { type: "agent", agent_id: id, agent_name_key: nameKey(agent), required: true };
    }
    const id = key.slice(5);
    if (!companyUserIds.has(id)) {
      throw new Error(`reverse sync ${type} participant is not an active company-scoped user`);
    }
    return { type: "user", user_id: id, required: true };
  });
}

async function buildPatch(db: Db, previous: IssueSnapshot, next: IssueSnapshot, fields: ReverseSyncField[]) {
  const patch: Record<string, unknown> = {};
  if (fields.includes("assigneeAgentId")) {
    if (!next.assigneeAgentId) {
      patch.assignee = null;
    } else {
      const agent = await db.select({ name: agents.name, metadata: agents.metadata })
        .from(agents)
        .where(and(eq(agents.id, next.assigneeAgentId), eq(agents.companyId, next.companyId)))
        .then((rows) => rows[0] ?? null);
      if (!agent) throw new Error("reverse sync assignee is not a company-scoped agent");
      patch.assignee = nameKey(agent);
    }
  }
  if (fields.includes("projectId")) {
    if (!next.projectId) {
      patch.project = null;
    } else {
      const project = await db.select({ id: projects.id, name: projects.name })
        .from(projects)
        .where(and(eq(projects.id, next.projectId), eq(projects.companyId, next.companyId)))
        .then((rows) => rows[0] ?? null);
      if (!project) throw new Error("reverse sync project is not company-scoped");
      patch.project = project;
    }
  }
  if (fields.includes("labels")) {
    const before = new Set(syncedLabelNames(previous));
    const after = new Set(syncedLabelNames(next));
    patch.labels = {
      add: [...after].filter((name) => !before.has(name)),
      removal_intent: [...before].filter((name) => !after.has(name)),
    };
  }
  if (fields.includes("reviewers")) patch.reviewers = await governanceValues(db, next, "review");
  if (fields.includes("approvers")) patch.approvers = await governanceValues(db, next, "approval");
  if (fields.includes("executionPolicy")) patch.execution_policy = next.executionPolicy ?? null;
  return patch;
}

export function hermesKanbanReverseSyncService(db: Db, options: { commandRunner?: CommandRunner } = {}) {
  const commandRunner = options.commandRunner ?? defaultCommandRunner;
  return {
    async syncCommittedIssueUpdate(input: {
      previous: IssueSnapshot;
      next: IssueSnapshot;
      actor: { actorType: "user" | "agent"; actorId: string };
    }): Promise<HermesKanbanReverseSyncResult> {
      const { previous, next } = input;
      const fields = changedFields(previous, next);
      if (next.originKind !== HERMES_KANBAN_TASK_ORIGIN_KIND || !next.originId || fields.length === 0) {
        return { attempted: false, accepted: false, pending: false, warning: null, fields: [] };
      }

      const actor = `${input.actor.actorType}:${input.actor.actorId}`;
      const mark = async (status: "accepted" | "pending" | "failed", warning: string | null) => {
        await db.update(issues).set({
          executionState: mergeReverseSyncState(next.executionState, { fields, status, warning }),
        }).where(and(eq(issues.id, next.id), eq(issues.companyId, next.companyId)));
      };

      if (next.status === "in_progress" && fields.includes("assigneeAgentId")) {
        const warning = "Running Hermes task reassignment requires explicit interrupt/requeue; canonical routing was not changed.";
        await mark("failed", warning);
        return { attempted: true, accepted: false, pending: false, warning, fields };
      }
      if (fields.includes("executionPolicy") && isPolicyLoosening(previous.executionPolicy, next.executionPolicy)) {
        const warning = "Execution policy or governance loosening requires board/operator authority before Hermes sync.";
        await mark("failed", warning);
        return { attempted: true, accepted: false, pending: false, warning, fields };
      }

      await mark("pending", null);
      try {
        const configuredBoard = resolveHermesKanbanBoard();
        const configuredDbPath = resolveHermesKanbanDbPath();
        const configuredCompanyId = resolveHermesKanbanCompanyId();
        const source = projectionSource(next.executionState);
        const canonicalDbPath = configuredDbPath ? realpathSync(configuredDbPath) : null;
        if (
          !configuredBoard
          || !canonicalDbPath
          || !configuredCompanyId
          || source?.board !== configuredBoard
          || source?.dbPath !== canonicalDbPath
          || source?.companyId !== configuredCompanyId
          || next.companyId !== configuredCompanyId
        ) {
          const warning = "Hermes reverse sync source binding does not match the issue board, database, and company projection identity.";
          await mark("failed", warning);
          return { attempted: true, accepted: false, pending: false, warning, fields };
        }
        const patch = await buildPatch(db, previous, next, fields);
        const response = await commandRunner({
          taskId: next.originId,
          patch,
          actor,
          expectedOriginFingerprint: next.originFingerprint,
          board: configuredBoard,
          dbPath: canonicalDbPath,
        });
        if (response.ok !== true) {
          const warning = typeof response.error === "string" ? response.error : "Hermes reverse sync was rejected";
          await mark("failed", warning);
          return { attempted: true, accepted: false, pending: false, warning, fields };
        }
        await mark("accepted", null);
        return { attempted: true, accepted: true, pending: false, warning: null, fields };
      } catch (error) {
        const warning = error instanceof Error ? error.message : "Hermes reverse sync failed";
        logger.warn({ error, issueId: next.id, taskId: next.originId }, "Hermes Kanban reverse sync failed");
        await mark("failed", warning);
        return { attempted: true, accepted: false, pending: false, warning, fields };
      }
    },
  };
}
