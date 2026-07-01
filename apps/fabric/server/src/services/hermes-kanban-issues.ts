import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { and, eq, inArray, isNull, sql } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { companies, issueRelations, issues } from "@paperclipai/db";
import { logger } from "../middleware/logger.js";
import { fabricEnv } from "../fabric-env.js";

export const HERMES_KANBAN_TASK_ORIGIN_KIND = "hermes_kanban_task";
const HERMES_KANBAN_SYNC_HEADER = "X-Hermes-Kanban-Sync";
const HERMES_KANBAN_SYNC_MESSAGE_HEADER = "X-Hermes-Kanban-Sync-Message";

const HERMES_KANBAN_OPT_IN_MESSAGE =
  "Hermes Kanban projection requires explicit FABRIC_HERMES_KANBAN_DB and FABRIC_HERMES_KANBAN_COMPANY_ID (or PAPERCLIP_ aliases).";

type HermesKanbanTaskRow = {
  id: string;
  title: string;
  body: string;
  assignee: string | null;
  status: string;
  priority: number;
  tenant: string | null;
  workspace_path: string | null;
  created_at: number | null;
  started_at: number | null;
  completed_at: number | null;
  last_heartbeat_at: number | null;
  result: string | null;
  block_kind: string | null;
};

type HermesKanbanRunRow = {
  task_id: string;
  summary: string | null;
  error: string | null;
  ended_at: number | null;
  last_heartbeat_at: number | null;
  metadata: string | null;
};

type HermesKanbanBlockEventRow = {
  task_id: string;
  payload: string | null;
};

type HermesKanbanTaskLinkRow = {
  parent_id: string;
  child_id: string;
};

type HermesKanbanSnapshotTask = {
  id: string;
  title: string;
  body: string;
  assignee: string | null;
  status: string;
  priority: number;
  tenant: string | null;
  workspacePath: string | null;
  createdAt: Date | null;
  startedAt: Date | null;
  completedAt: Date | null;
  lastHeartbeatAt: Date | null;
  result: string | null;
  blockKind: string | null;
  blockedReason: string | null;
  latestRunSummary: string | null;
  latestRunError: string | null;
  updatedAt: Date;
};

type HermesKanbanSnapshot = {
  dbPath: string;
  tasks: HermesKanbanSnapshotTask[];
  links: HermesKanbanTaskLinkRow[];
};

type HermesKanbanIssueSeed = {
  title: string;
  description: string | null;
  status: typeof issues.$inferInsert.status;
  priority: typeof issues.$inferInsert.priority;
  executionAgentNameKey: string | null;
  startedAt: Date | null;
  completedAt: Date | null;
  updatedAt: Date;
  createdAt: Date;
  originFingerprint: string;
};

export type HermesKanbanSyncStatus = "ok" | "unavailable" | "error";

export type HermesKanbanSyncResult = {
  status: HermesKanbanSyncStatus;
  message: string | null;
  syncedCount: number;
  projectedCount: number;
  dbPath: string | null;
};

type HermesKanbanProjectionScope =
  | { allowed: true }
  | { allowed: false; status: HermesKanbanSyncStatus; message: string | null };

export function hermesKanbanSyncHeaders(result: HermesKanbanSyncResult): Record<string, string> {
  const headers: Record<string, string> = {
    [HERMES_KANBAN_SYNC_HEADER]: result.status,
  };
  if (result.message) headers[HERMES_KANBAN_SYNC_MESSAGE_HEADER] = result.message;
  return headers;
}

export function readHermesKanbanSyncStatus(headers: Headers | Pick<Headers, "get">) {
  return {
    status: headers.get(HERMES_KANBAN_SYNC_HEADER),
    message: headers.get(HERMES_KANBAN_SYNC_MESSAGE_HEADER),
  };
}

export function resolveHermesKanbanDbPath(env: NodeJS.ProcessEnv = process.env): string | null {
  const configured = fabricEnv("HERMES_KANBAN_DB") ?? env.HERMES_KANBAN_DB;
  if (!configured) return null;
  return configured.startsWith("~/") ? `${homedir()}/${configured.slice(2)}` : configured;
}

export async function syncHermesKanbanIssues(db: Db, companyId: string): Promise<HermesKanbanSyncResult> {
  const scope = await resolveHermesKanbanProjectionScope(db, companyId);
  if (!scope.allowed) {
    return {
      status: scope.status,
      message: scope.message,
      syncedCount: 0,
      projectedCount: 0,
      dbPath: null,
    };
  }

  const dbPath = resolveHermesKanbanDbPath();
  if (!dbPath) {
    return {
      status: "unavailable",
      message: HERMES_KANBAN_OPT_IN_MESSAGE,
      syncedCount: 0,
      projectedCount: 0,
      dbPath: null,
    };
  }

  if (!existsSync(dbPath)) {
    return {
      status: "unavailable",
      message: "Hermes Kanban DB not found.",
      syncedCount: 0,
      projectedCount: 0,
      dbPath,
    };
  }

  try {
    const snapshot = readHermesKanbanSnapshot(dbPath);
    const projectedCount = snapshot.tasks.length;
    if (snapshot.tasks.length === 0) {
      return { status: "ok", message: null, syncedCount: 0, projectedCount, dbPath };
    }

    const taskIds = snapshot.tasks.map((task) => task.id);
    const existingRows = await db
      .select({
        id: issues.id,
        originId: issues.originId,
        title: issues.title,
        description: issues.description,
        status: issues.status,
        priority: issues.priority,
        executionAgentNameKey: issues.executionAgentNameKey,
        startedAt: issues.startedAt,
        completedAt: issues.completedAt,
        createdAt: issues.createdAt,
        updatedAt: issues.updatedAt,
        originFingerprint: issues.originFingerprint,
      })
      .from(issues)
      .where(
        and(
          eq(issues.companyId, companyId),
          eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND),
          inArray(issues.originId, taskIds),
          isNull(issues.hiddenAt),
        ),
      );
    const existingByTaskId = new Map(existingRows.map((row) => [row.originId ?? "", row]));
    const issueIdByTaskId = new Map<string, string>();

    let syncedCount = 0;
    for (const task of snapshot.tasks) {
      const seed = buildHermesKanbanIssueSeed(task);
      const existing = existingByTaskId.get(task.id) ?? null;
      if (!existing) {
        const issue = await createProjectedIssue(db, companyId, task.id, seed);
        issueIdByTaskId.set(task.id, issue.id);
        syncedCount += 1;
        continue;
      }

      issueIdByTaskId.set(task.id, existing.id);
      const changed = await updateProjectedIssueIfNeeded(db, existing.id, existing, seed);
      if (changed) syncedCount += 1;
    }

    const childTaskIds = [...new Set(snapshot.links.map((link) => link.child_id))];
    for (const childTaskId of childTaskIds) {
      const childIssueId = issueIdByTaskId.get(childTaskId);
      if (!childIssueId) continue;
      const blockerIssueIds = [...new Set(
        snapshot.links
          .filter((link) => link.child_id === childTaskId)
          .map((link) => issueIdByTaskId.get(link.parent_id) ?? null)
          .filter((value): value is string => Boolean(value)),
      )];
      const relationsChanged = await syncProjectedIssueBlockedBy(db, companyId, childIssueId, blockerIssueIds);
      if (relationsChanged) syncedCount += 1;
    }

    return { status: "ok", message: null, syncedCount, projectedCount, dbPath };
  } catch (error) {
    logger.warn({ error, companyId, dbPath }, "Failed to sync Hermes Kanban tasks into Fabric issues");
    return {
      status: "error",
      message: error instanceof Error ? error.message : "Failed to sync Hermes Kanban tasks",
      syncedCount: 0,
      projectedCount: 0,
      dbPath,
    };
  }
}

async function resolveHermesKanbanProjectionScope(_db: Db, companyId: string): Promise<HermesKanbanProjectionScope> {
  const configuredCompanyId = asString(fabricEnv("HERMES_KANBAN_COMPANY_ID") ?? process.env.HERMES_KANBAN_COMPANY_ID);
  if (!configuredCompanyId) {
    return { allowed: false, status: "unavailable", message: HERMES_KANBAN_OPT_IN_MESSAGE };
  }
  if (configuredCompanyId === companyId) return { allowed: true };
  return { allowed: false, status: "ok", message: null };
}

function readHermesKanbanSnapshot(dbPath: string): HermesKanbanSnapshot {
  const sqlite = new DatabaseSync(dbPath, { readOnly: true });
  try {
    const taskRows = sqlite.prepare(`
      SELECT
        id,
        title,
        COALESCE(body, '') AS body,
        assignee,
        status,
        COALESCE(priority, 0) AS priority,
        tenant,
        workspace_path,
        created_at,
        started_at,
        completed_at,
        last_heartbeat_at,
        result,
        block_kind
      FROM tasks
      WHERE status != 'archived'
      ORDER BY created_at DESC
    `).all() as HermesKanbanTaskRow[];

    const latestRunRows = sqlite.prepare(`
      SELECT tr.task_id, tr.summary, tr.error, tr.ended_at, tr.last_heartbeat_at, tr.metadata
      FROM task_runs tr
      INNER JOIN (
        SELECT task_id, MAX(id) AS max_id
        FROM task_runs
        GROUP BY task_id
      ) latest ON latest.task_id = tr.task_id AND latest.max_id = tr.id
    `).all() as HermesKanbanRunRow[];

    const latestBlockedEventRows = sqlite.prepare(`
      SELECT te.task_id, te.payload
      FROM task_events te
      INNER JOIN (
        SELECT task_id, MAX(id) AS max_id
        FROM task_events
        WHERE kind = 'blocked'
        GROUP BY task_id
      ) latest ON latest.task_id = te.task_id AND latest.max_id = te.id
    `).all() as HermesKanbanBlockEventRow[];

    const links = sqlite.prepare(`
      SELECT parent_id, child_id
      FROM task_links
    `).all() as HermesKanbanTaskLinkRow[];

    const latestRunByTaskId = new Map(latestRunRows.map((row) => [row.task_id, row]));
    const blockedByTaskId = new Map(latestBlockedEventRows.map((row) => [row.task_id, row]));

    return {
      dbPath,
      tasks: taskRows.map((task) => {
        const latestRun = latestRunByTaskId.get(task.id) ?? null;
        const blocked = blockedByTaskId.get(task.id) ?? null;
        const blockedPayload = parseJsonObject(blocked?.payload);
        const blockedReason = asString(blockedPayload?.reason);
        const createdAt = epochSecondsToDate(task.created_at);
        const startedAt = epochSecondsToDate(task.started_at);
        const completedAt = epochSecondsToDate(task.completed_at);
        const lastHeartbeatAt = epochSecondsToDate(task.last_heartbeat_at ?? latestRun?.last_heartbeat_at ?? null);
        const updatedAt = latestDate([
          completedAt,
          lastHeartbeatAt,
          epochSecondsToDate(latestRun?.ended_at ?? null),
          startedAt,
          createdAt,
        ]) ?? new Date();
        return {
          id: task.id,
          title: task.title,
          body: task.body,
          assignee: asString(task.assignee),
          status: task.status,
          priority: Number.isFinite(task.priority) ? task.priority : 0,
          tenant: asString(task.tenant),
          workspacePath: asString(task.workspace_path),
          createdAt,
          startedAt,
          completedAt,
          lastHeartbeatAt,
          result: asString(task.result),
          blockKind: asString(task.block_kind),
          blockedReason,
          latestRunSummary: asString(latestRun?.summary),
          latestRunError: asString(latestRun?.error),
          updatedAt,
        };
      }),
      links,
    };
  } finally {
    sqlite.close();
  }
}

function buildHermesKanbanIssueSeed(task: HermesKanbanSnapshotTask): HermesKanbanIssueSeed {
  const createdAt = task.createdAt ?? task.updatedAt;
  const description = buildHermesKanbanIssueDescription(task);
  return {
    title: task.title,
    description,
    status: mapHermesKanbanTaskStatus(task.status),
    priority: mapHermesKanbanTaskPriority(task.priority),
    executionAgentNameKey: task.assignee,
    startedAt: task.startedAt,
    completedAt: task.completedAt,
    updatedAt: task.updatedAt,
    createdAt,
    originFingerprint: `hermes-kanban:${task.id}`,
  };
}

async function createProjectedIssue(
  db: Db,
  companyId: string,
  taskId: string,
  seed: HermesKanbanIssueSeed,
) {
  return db.transaction(async (tx) => {
    const [maxRow] = await tx
      .select({ maxNum: sql<number>`coalesce(max(${issues.issueNumber}), 0)` })
      .from(issues)
      .where(eq(issues.companyId, companyId));
    const currentMax = maxRow?.maxNum ?? 0;
    const [company] = await tx
      .update(companies)
      .set({ issueCounter: sql`greatest(${companies.issueCounter}, ${currentMax}) + 1` })
      .where(eq(companies.id, companyId))
      .returning({ issueCounter: companies.issueCounter, issuePrefix: companies.issuePrefix });
    const issueNumber = company.issueCounter;
    const identifier = `${company.issuePrefix}-${issueNumber}`;
    const [issue] = await tx.insert(issues).values({
      companyId,
      title: seed.title,
      description: seed.description,
      status: seed.status,
      workMode: "standard",
      priority: seed.priority,
      executionAgentNameKey: seed.executionAgentNameKey,
      issueNumber,
      identifier,
      originKind: HERMES_KANBAN_TASK_ORIGIN_KIND,
      originId: taskId,
      originFingerprint: seed.originFingerprint,
      requestDepth: 0,
      createdAt: seed.createdAt,
      updatedAt: seed.updatedAt,
      startedAt: seed.startedAt,
      completedAt: seed.completedAt,
    }).returning({ id: issues.id });
    return issue;
  });
}

async function updateProjectedIssueIfNeeded(
  db: Db,
  issueId: string,
  existing: {
    title: string;
    description: string | null;
    status: string;
    priority: string;
    executionAgentNameKey: string | null;
    startedAt: Date | null;
    completedAt: Date | null;
    createdAt: Date;
    updatedAt: Date;
    originFingerprint: string;
  },
  seed: HermesKanbanIssueSeed,
) {
  const patch: Partial<typeof issues.$inferInsert> = {};
  if (existing.title !== seed.title) patch.title = seed.title;
  if ((existing.description ?? null) !== seed.description) patch.description = seed.description;
  if (existing.status !== seed.status) patch.status = seed.status;
  if (existing.priority !== seed.priority) patch.priority = seed.priority;
  if ((existing.executionAgentNameKey ?? null) !== seed.executionAgentNameKey) {
    patch.executionAgentNameKey = seed.executionAgentNameKey;
  }
  if (dateMs(existing.startedAt) !== dateMs(seed.startedAt)) patch.startedAt = seed.startedAt;
  if (dateMs(existing.completedAt) !== dateMs(seed.completedAt)) patch.completedAt = seed.completedAt;
  if (existing.originFingerprint !== seed.originFingerprint) patch.originFingerprint = seed.originFingerprint;
  if (dateMs(existing.createdAt) !== dateMs(seed.createdAt)) patch.createdAt = seed.createdAt;
  if (dateMs(existing.updatedAt) !== dateMs(seed.updatedAt)) patch.updatedAt = seed.updatedAt;
  if (Object.keys(patch).length === 0) return false;
  await db.update(issues).set(patch).where(eq(issues.id, issueId));
  return true;
}

async function syncProjectedIssueBlockedBy(db: Db, companyId: string, issueId: string, blockerIssueIds: string[]) {
  const existingRows = await db
    .select({ issueId: issueRelations.issueId })
    .from(issueRelations)
    .where(
      and(
        eq(issueRelations.companyId, companyId),
        eq(issueRelations.relatedIssueId, issueId),
        eq(issueRelations.type, "blocks"),
      ),
    );
  const current = existingRows.map((row) => row.issueId).sort();
  const next = [...blockerIssueIds].sort();
  if (current.length === next.length && current.every((value, index) => value === next[index])) {
    return false;
  }

  await db.delete(issueRelations).where(
    and(
      eq(issueRelations.companyId, companyId),
      eq(issueRelations.relatedIssueId, issueId),
      eq(issueRelations.type, "blocks"),
    ),
  );
  if (next.length > 0) {
    await db.insert(issueRelations).values(next.map((blockerIssueId) => ({
      companyId,
      issueId: blockerIssueId,
      relatedIssueId: issueId,
      type: "blocks" as const,
      createdByAgentId: null,
      createdByUserId: null,
    })));
  }
  return true;
}

function buildHermesKanbanIssueDescription(task: HermesKanbanSnapshotTask) {
  const sections: string[] = [];
  const includeDetails = isHermesKanbanSensitiveProjectionEnabled();
  const body = task.body.trim();
  if (includeDetails && body.length > 0) sections.push(body);

  const metadataLines = [
    `Hermes Kanban task: ${task.id}`,
    `Status: ${task.status}`,
    `Priority: ${task.priority}`,
    task.assignee ? `Assignee: ${task.assignee}` : null,
    includeDetails && task.workspacePath ? `Workspace: ${task.workspacePath}` : null,
    includeDetails && task.tenant ? `Tenant: ${task.tenant}` : null,
    task.blockKind ? `Block kind: ${task.blockKind}` : null,
  ].filter((value): value is string => Boolean(value));
  sections.push(metadataLines.join("\n"));

  if (includeDetails && task.blockedReason) {
    sections.push(`Latest block reason:\n${task.blockedReason}`);
  }
  if (includeDetails && task.latestRunSummary) {
    sections.push(`Latest run summary:\n${task.latestRunSummary}`);
  }
  if (includeDetails && task.latestRunError) {
    sections.push(`Latest run error:\n${task.latestRunError}`);
  }
  if (includeDetails && task.result) {
    sections.push(`Task result:\n${task.result}`);
  }

  const compact = sections
    .map((section) => section.trim())
    .filter((section) => section.length > 0)
    .join("\n\n");
  return compact.length > 0 ? compact : null;
}

function isHermesKanbanSensitiveProjectionEnabled() {
  const configured = fabricEnv("HERMES_KANBAN_INCLUDE_DETAILS") ?? process.env.HERMES_KANBAN_INCLUDE_DETAILS;
  return configured === "1" || configured?.toLowerCase() === "true";
}

function mapHermesKanbanTaskStatus(status: string): typeof issues.$inferInsert.status {
  switch (status) {
    case "running":
      return "in_progress";
    case "blocked":
      return "blocked";
    case "done":
      return "done";
    case "cancelled":
    case "canceled":
      return "cancelled";
    case "in_review":
      return "in_review";
    case "backlog":
    case "triage":
      return "backlog";
    case "todo":
    case "ready":
    default:
      return "todo";
  }
}

function mapHermesKanbanTaskPriority(priority: number): typeof issues.$inferInsert.priority {
  if (priority >= 90) return "critical";
  if (priority >= 70) return "high";
  if (priority >= 40) return "medium";
  return "low";
}

function epochSecondsToDate(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
  return new Date(value * 1000);
}

function latestDate(values: Array<Date | null | undefined>) {
  let best: Date | null = null;
  for (const value of values) {
    if (!value) continue;
    if (!best || value.getTime() > best.getTime()) best = value;
  }
  return best;
}

function dateMs(value: Date | null | undefined) {
  return value ? value.getTime() : null;
}

function parseJsonObject(value: string | null | undefined) {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function asString(value: unknown) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
