import { accessSync, constants, existsSync } from "node:fs";
import { homedir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { and, eq, inArray, isNull, or, sql } from "drizzle-orm";
import type { Db } from "@hermes-fabric/db";
import type { SourceTrustMetadata } from "@hermes-fabric/shared";
import {
  agents,
  approvals,
  companies,
  issueApprovals,
  issueLabels,
  issueRelations,
  issues,
  labels,
  projects,
  projectWorkspaces,
} from "@hermes-fabric/db";
import { logger } from "../middleware/logger.js";
import { fabricEnv } from "../fabric-env.js";

export const HERMES_KANBAN_TASK_ORIGIN_KIND = "hermes_kanban_task";
const HERMES_KANBAN_SYNC_HEADER = "X-Hermes-Kanban-Sync";
const HERMES_KANBAN_SYNC_MESSAGE_HEADER = "X-Hermes-Kanban-Sync-Message";
const HERMES_KANBAN_SYNC_DEFAULT_INTERVAL_MS = 15_000;
const HERMES_KANBAN_SYNC_MIN_INTERVAL_MS = 1_000;
const HERMES_KANBAN_SYNC_MAX_BACKOFF_MS = 60_000;

const HERMES_KANBAN_OPT_IN_MESSAGE =
  "Hermes Kanban projection requires explicit FABRIC_HERMES_KANBAN_DB and FABRIC_HERMES_KANBAN_COMPANY_ID (or HERMES_FABRIC_ aliases).";

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

type HermesKanbanEventRow = {
  id: number;
  task_id: string;
  kind: string;
  payload: string | null;
  created_at: number | null;
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
  latestRunMetadata: Record<string, unknown> | null;
  events: HermesKanbanSnapshotEvent[];
  parentTaskIds: string[];
  childTaskIds: string[];
  updatedAt: Date;
};

type HermesKanbanSnapshotEvent = {
  id: number;
  kind: string;
  payload: Record<string, unknown> | null;
  createdAt: Date | null;
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
  assigneeAgentId: string | null;
  projectId: string | null;
  projectWorkspaceId: string | null;
  executionPolicy: Record<string, unknown> | null;
  executionState: Record<string, unknown> | null;
  sourceTrust: SourceTrustMetadata | null;
  labelSpecs: ProjectionLabelSpec[];
  previousProjectionLabelNames: string[];
  approvalSpecs: ProjectionApprovalSpec[];
};

type ProjectionLabelSpec = { name: string; color: string };
type ProjectionApprovalSpec = {
  type: string;
  requestedByAgentId: string | null;
  payload: Record<string, unknown>;
  fingerprint: string;
};

type ProjectionMetadata = {
  fabric: Record<string, unknown>;
  hermesAgency: Record<string, unknown>;
  warnings: string[];
  provenance: string[];
  sourceTrust: Record<string, unknown> | null;
};

export type HermesKanbanSyncStatus = "ok" | "unavailable" | "error";

export type HermesKanbanSyncResult = {
  status: HermesKanbanSyncStatus;
  message: string | null;
  syncedCount: number;
  projectedCount: number;
  dbPath: string | null;
};

export type HermesKanbanProjectionStatus = {
  enabled: boolean;
  dbPath: string | null;
  companyId: string | null;
  lastSyncAt: string | null;
  lastStatus: HermesKanbanSyncStatus | "disabled";
  projectedCount: number;
  syncedCount: number;
  lastError: string | null;
  intervalMs: number;
  consecutiveFailures: number;
  nextSyncAt: string | null;
};

type HermesKanbanProjectionScope =
  | { allowed: true }
  | { allowed: false; status: HermesKanbanSyncStatus; message: string | null };

let lastHermesKanbanSync: (HermesKanbanSyncResult & { syncedAt: Date }) | null = null;
let hermesKanbanSyncLogState: { key: string; repeats: number } | null = null;
let hermesKanbanSyncWorkerState: {
  intervalMs: number;
  consecutiveFailures: number;
  nextSyncAt: Date | null;
} = {
  intervalMs: HERMES_KANBAN_SYNC_DEFAULT_INTERVAL_MS,
  consecutiveFailures: 0,
  nextSyncAt: null,
};

export function hermesKanbanSyncHeaders(result: HermesKanbanSyncResult): Record<string, string> {
  const headers: Record<string, string> = {
    [HERMES_KANBAN_SYNC_HEADER]: result.status,
  };
  const headerMessage = sanitizeHeaderValue(result.message);
  if (headerMessage) headers[HERMES_KANBAN_SYNC_MESSAGE_HEADER] = headerMessage;
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

export function resolveHermesKanbanCompanyId(env: NodeJS.ProcessEnv = process.env): string | null {
  return asString(fabricEnv("HERMES_KANBAN_COMPANY_ID") ?? env.HERMES_KANBAN_COMPANY_ID);
}

export function resolveHermesKanbanSyncIntervalMs(env: NodeJS.ProcessEnv = process.env): number {
  const configured = fabricEnv("HERMES_KANBAN_SYNC_INTERVAL_MS") ?? env.HERMES_KANBAN_SYNC_INTERVAL_MS;
  if (!configured) return HERMES_KANBAN_SYNC_DEFAULT_INTERVAL_MS;
  const parsed = Number.parseInt(configured, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return HERMES_KANBAN_SYNC_DEFAULT_INTERVAL_MS;
  return Math.max(HERMES_KANBAN_SYNC_MIN_INTERVAL_MS, parsed);
}

export function getHermesKanbanProjectionStatus(): HermesKanbanProjectionStatus {
  const dbPath = resolveHermesKanbanDbPath();
  const companyId = resolveHermesKanbanCompanyId();
  const enabled = Boolean(dbPath && companyId);
  return {
    enabled,
    dbPath,
    companyId,
    lastSyncAt: lastHermesKanbanSync?.syncedAt.toISOString() ?? null,
    lastStatus: lastHermesKanbanSync?.status ?? (enabled ? "unavailable" : "disabled"),
    projectedCount: lastHermesKanbanSync?.projectedCount ?? 0,
    syncedCount: lastHermesKanbanSync?.syncedCount ?? 0,
    lastError: lastHermesKanbanSync?.status === "error" ? lastHermesKanbanSync.message : null,
    intervalMs: hermesKanbanSyncWorkerState.intervalMs,
    consecutiveFailures: hermesKanbanSyncWorkerState.consecutiveFailures,
    nextSyncAt: hermesKanbanSyncWorkerState.nextSyncAt?.toISOString() ?? null,
  };
}

export function createHermesKanbanProjectionSyncWorker(db: Db) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let running = false;
  let stopped = true;
  const intervalMs = resolveHermesKanbanSyncIntervalMs();
  hermesKanbanSyncWorkerState = {
    intervalMs,
    consecutiveFailures: 0,
    nextSyncAt: null,
  };

  const schedule = (delayMs: number) => {
    if (stopped) return;
    const nextSyncAt = new Date(Date.now() + delayMs);
    hermesKanbanSyncWorkerState = { ...hermesKanbanSyncWorkerState, intervalMs, nextSyncAt };
    timer = setTimeout(() => {
      void tick();
    }, delayMs);
    timer.unref?.();
  };

  const tick = async () => {
    if (stopped) return;
    if (running) {
      schedule(intervalMs);
      return;
    }
    running = true;
    hermesKanbanSyncWorkerState = { ...hermesKanbanSyncWorkerState, nextSyncAt: null };
    let failed = false;
    try {
      const companyId = resolveHermesKanbanCompanyId();
      if (!companyId) {
        lastHermesKanbanSync = null;
        hermesKanbanSyncWorkerState = { ...hermesKanbanSyncWorkerState, consecutiveFailures: 0 };
        return;
      }
      const result = await syncHermesKanbanIssues(db, companyId);
      failed = result.status === "error";
    } catch (error) {
      failed = true;
      rememberHermesKanbanSync({
        status: "error",
        message: error instanceof Error ? error.message : "Hermes Kanban projection background sync failed",
        syncedCount: 0,
        projectedCount: 0,
        dbPath: resolveHermesKanbanDbPath(),
      }, resolveHermesKanbanCompanyId() ?? "unknown");
    } finally {
      running = false;
      if (!stopped) {
        const previousFailures = hermesKanbanSyncWorkerState.consecutiveFailures;
        const consecutiveFailures = failed ? previousFailures + 1 : 0;
        const backoffMs = failed
          ? Math.min(intervalMs * (2 ** Math.min(consecutiveFailures - 1, 4)), HERMES_KANBAN_SYNC_MAX_BACKOFF_MS)
          : intervalMs;
        hermesKanbanSyncWorkerState = { ...hermesKanbanSyncWorkerState, intervalMs, consecutiveFailures };
        schedule(backoffMs);
      }
    }
  };

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      schedule(0);
    },
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
      timer = null;
      hermesKanbanSyncWorkerState = { ...hermesKanbanSyncWorkerState, nextSyncAt: null };
    },
    triggerNow: tick,
  };
}

export function logHermesKanbanProjectionStartupStatus() {
  const dbPath = resolveHermesKanbanDbPath();
  const companyId = resolveHermesKanbanCompanyId();
  if (!dbPath || !companyId) {
    logger.info({ enabled: false, dbPath, companyId }, HERMES_KANBAN_OPT_IN_MESSAGE);
    return;
  }
  try {
    assertReadableFile(dbPath);
    logger.info({ enabled: true, dbPath, companyId }, "Hermes Kanban projection configured");
  } catch (error) {
    logger.warn({ enabled: true, dbPath, companyId, error }, "Hermes Kanban projection configured but DB is not readable");
  }
}

export async function syncHermesKanbanIssues(db: Db, companyId: string): Promise<HermesKanbanSyncResult> {
  const dbPath = resolveHermesKanbanDbPath();
  const configuredCompanyId = resolveHermesKanbanCompanyId();
  const scope = await resolveHermesKanbanProjectionScope(db, companyId, configuredCompanyId);
  if (!scope.allowed) {
    return rememberHermesKanbanSync({
      status: scope.status,
      message: scope.message,
      syncedCount: 0,
      projectedCount: 0,
      dbPath,
    }, companyId);
  }

  if (!dbPath) {
    return rememberHermesKanbanSync({
      status: "unavailable",
      message: HERMES_KANBAN_OPT_IN_MESSAGE,
      syncedCount: 0,
      projectedCount: 0,
      dbPath: null,
    }, companyId);
  }

  try {
    assertReadableFile(dbPath);
  } catch (error) {
    return rememberHermesKanbanSync({
      status: configuredCompanyId ? "error" : "unavailable",
      message: error instanceof Error ? error.message : "Hermes Kanban DB is not readable.",
      syncedCount: 0,
      projectedCount: 0,
      dbPath,
    }, companyId);
  }

  try {
    const snapshot = readHermesKanbanSnapshot(dbPath);
    const projectedCount = snapshot.tasks.length;
    const taskIds = snapshot.tasks.map((task) => task.id);
    const existingRows = await db
      .select({
        id: issues.id,
        issueNumber: issues.issueNumber,
        originId: issues.originId,
        title: issues.title,
        description: issues.description,
        status: issues.status,
        priority: issues.priority,
        assigneeAgentId: issues.assigneeAgentId,
        projectId: issues.projectId,
        projectWorkspaceId: issues.projectWorkspaceId,
        executionAgentNameKey: issues.executionAgentNameKey,
        executionPolicy: issues.executionPolicy,
        executionState: issues.executionState,
        sourceTrust: issues.sourceTrust,
        startedAt: issues.startedAt,
        completedAt: issues.completedAt,
        createdAt: issues.createdAt,
        updatedAt: issues.updatedAt,
        hiddenAt: issues.hiddenAt,
        originFingerprint: issues.originFingerprint,
      })
      .from(issues)
      .where(
        and(
          eq(issues.companyId, companyId),
          eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND),
        ),
      );
    // Deduplicate: prefer unhidden rows, then the most recently updated row. If timestamps
    // tie, preserve the lower issue number (the projection created first) deterministically.
    // This prevents concurrent sync races from creating duplicate projections for the same task.
    const dedupedRows = deduplicateExistingRows(existingRows);
    const existingByTaskId = new Map(dedupedRows.map((row) => [row.originId ?? "", row]));
    const issueIdByTaskId = new Map<string, string>();
    const currentTaskIds = new Set(taskIds);
    const staleProjectedIssueIds = existingRows
      .filter((row) => row.originId && !currentTaskIds.has(row.originId) && row.hiddenAt === null)
      .map((row) => row.id);

    let syncedCount = 0;

    // Hide duplicate unhidden rows that were not selected as the canonical row.
    const duplicateUnhiddenIds = findDuplicateUnhiddenIds(existingRows, existingByTaskId);
    if (duplicateUnhiddenIds.length > 0) {
      const dupRelationsDeleted = await deleteProjectedIssueRelations(db, companyId, duplicateUnhiddenIds);
      if (dupRelationsDeleted) syncedCount += 1;
      const dupHidden = await hideProjectedIssues(db, duplicateUnhiddenIds);
      if (dupHidden) syncedCount += 1;
    }
    for (const task of snapshot.tasks) {
      const existing = existingByTaskId.get(task.id) ?? null;
      const seed = await buildHermesKanbanIssueSeed(db, companyId, task, existing);
      if (!existing) {
        const issue = await createProjectedIssue(db, companyId, task.id, seed);
        issueIdByTaskId.set(task.id, issue.id);
        const enrichChanged = await syncProjectedIssueEnrichment(db, companyId, issue.id, seed);
        syncedCount += 1;
        if (enrichChanged) syncedCount += 1;
        continue;
      }

      issueIdByTaskId.set(task.id, existing.id);
      const changed = await updateProjectedIssueIfNeeded(db, existing.id, existing, seed);
      const enrichChanged = await syncProjectedIssueEnrichment(db, companyId, existing.id, seed);
      if (changed || enrichChanged) syncedCount += 1;
    }

    for (const task of snapshot.tasks) {
      const childIssueId = issueIdByTaskId.get(task.id);
      if (!childIssueId) continue;
      const blockerIssueIds = [...new Set(
        snapshot.links
          .filter((link) => link.child_id === task.id)
          .map((link) => issueIdByTaskId.get(link.parent_id) ?? null)
          .filter((value): value is string => Boolean(value)),
      )];
      const relationsChanged = await syncProjectedIssueBlockedBy(db, companyId, childIssueId, blockerIssueIds);
      if (relationsChanged) syncedCount += 1;
    }

    if (staleProjectedIssueIds.length > 0) {
      const staleRelationsDeleted = await deleteProjectedIssueRelations(db, companyId, staleProjectedIssueIds);
      if (staleRelationsDeleted) syncedCount += 1;
      const staleHidden = await hideProjectedIssues(db, staleProjectedIssueIds);
      if (staleHidden) syncedCount += 1;
    }

    return rememberHermesKanbanSync({ status: "ok", message: null, syncedCount, projectedCount, dbPath }, companyId);
  } catch (error) {
    return rememberHermesKanbanSync({
      status: "error",
      message: classifyHermesKanbanSyncError(error),
      syncedCount: 0,
      projectedCount: 0,
      dbPath,
    }, companyId);
  }
}

async function resolveHermesKanbanProjectionScope(
  db: Db,
  companyId: string,
  configuredCompanyId: string | null,
): Promise<HermesKanbanProjectionScope> {
  if (!configuredCompanyId) {
    return { allowed: false, status: "unavailable", message: HERMES_KANBAN_OPT_IN_MESSAGE };
  }
  const [configuredCompany] = await db
    .select({ id: companies.id })
    .from(companies)
    .where(eq(companies.id, configuredCompanyId))
    .limit(1);
  if (!configuredCompany) {
    return {
      allowed: false,
      status: "error",
      message: `Configured Hermes Kanban company ${configuredCompanyId} was not found in Fabric.`,
    };
  }
  if (configuredCompanyId === companyId) return { allowed: true };
  return {
    allowed: false,
    status: "ok",
    message: `Hermes Kanban projection is scoped to company ${configuredCompanyId}; skipping company ${companyId}.`,
  };
}

function rememberHermesKanbanSync(result: HermesKanbanSyncResult, companyId: string): HermesKanbanSyncResult {
  lastHermesKanbanSync = { ...result, syncedAt: new Date() };
  const logContext = {
    companyId,
    dbPath: result.dbPath,
    status: result.status,
    projectedCount: result.projectedCount,
    syncedCount: result.syncedCount,
    message: result.message,
  };
  const logKey = `${result.status}:${result.message ?? ""}`;
  const repeated = hermesKanbanSyncLogState?.key === logKey;
  hermesKanbanSyncLogState = repeated
    ? { key: logKey, repeats: (hermesKanbanSyncLogState?.repeats ?? 0) + 1 }
    : { key: logKey, repeats: 0 };
  const repeatCount = hermesKanbanSyncLogState.repeats;
  const shouldLogRepeatedFailure = repeatCount === 0 || repeatCount === 1 || repeatCount % 10 === 0;

  if (result.status === "ok") {
    logger.debug(logContext, "Hermes Kanban projection sync completed");
  } else if (shouldLogRepeatedFailure) {
    const repeatedLogContext = repeatCount > 0 ? { ...logContext, repeatCount } : logContext;
    if (result.status === "unavailable") {
      logger.info(repeatedLogContext, "Hermes Kanban projection sync unavailable");
    } else {
      logger.warn(repeatedLogContext, "Hermes Kanban projection sync failed");
    }
  }
  return result;
}

function assertReadableFile(dbPath: string) {
  if (!existsSync(dbPath)) {
    throw new Error(`Hermes Kanban DB not found: ${dbPath}`);
  }
  try {
    accessSync(dbPath, constants.R_OK);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Hermes Kanban DB is not readable: ${message}`);
  }
}

function classifyHermesKanbanSyncError(error: unknown) {
  const message = error instanceof Error ? error.message : "Failed to sync Hermes Kanban tasks";
  if (/no such table|no such column/i.test(message)) {
    return `Hermes Kanban DB schema mismatch: ${message}`;
  }
  if (/SQLITE_CANTOPEN|permission|EACCES|EPERM/i.test(message)) {
    return `Hermes Kanban DB permission/open error: ${message}`;
  }
  return message;
}

function sanitizeHeaderValue(value: string | null | undefined) {
  if (!value) return null;
  return value.replace(/[\r\n\t\0]+/g, " ").replace(/[\u0001-\u001f\u007f]+/g, " ").trim();
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

    const taskEventColumns = new Set(
      (sqlite.prepare("PRAGMA table_info(task_events)").all() as Array<{ name: string }>).map((column) => column.name),
    );
    const eventCreatedAtSelect = taskEventColumns.has("created_at") ? "created_at" : "NULL AS created_at";
    const eventRows = sqlite.prepare(`
      SELECT id, task_id, kind, payload, ${eventCreatedAtSelect}
      FROM task_events
      ORDER BY id ASC
    `).all() as HermesKanbanEventRow[];

    const links = sqlite.prepare(`
      SELECT parent_id, child_id
      FROM task_links
    `).all() as HermesKanbanTaskLinkRow[];

    const latestRunByTaskId = new Map(latestRunRows.map((row) => [row.task_id, row]));
    const eventsByTaskId = new Map<string, HermesKanbanEventRow[]>();
    for (const event of eventRows) {
      const events = eventsByTaskId.get(event.task_id) ?? [];
      events.push(event);
      eventsByTaskId.set(event.task_id, events);
    }
    const parentIdsByChild = new Map<string, string[]>();
    const childIdsByParent = new Map<string, string[]>();
    for (const link of links) {
      parentIdsByChild.set(link.child_id, [...(parentIdsByChild.get(link.child_id) ?? []), link.parent_id]);
      childIdsByParent.set(link.parent_id, [...(childIdsByParent.get(link.parent_id) ?? []), link.child_id]);
    }

    return {
      dbPath,
      tasks: taskRows.map((task) => {
        const latestRun = latestRunByTaskId.get(task.id) ?? null;
        const taskEvents = eventsByTaskId.get(task.id) ?? [];
        const blocked = [...taskEvents].reverse().find((event) => event.kind === "blocked") ?? null;
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
          latestRunMetadata: parseJsonObject(latestRun?.metadata),
          events: taskEvents.map((event) => ({
            id: event.id,
            kind: event.kind,
            payload: parseJsonObject(event.payload),
            createdAt: epochSecondsToDate(event.created_at),
          })),
          parentTaskIds: parentIdsByChild.get(task.id) ?? [],
          childTaskIds: childIdsByParent.get(task.id) ?? [],
          updatedAt,
        };
      }),
      links,
    };
  } finally {
    sqlite.close();
  }
}

async function buildHermesKanbanIssueSeed(
  db: Db,
  companyId: string,
  task: HermesKanbanSnapshotTask,
  existing: {
    assigneeAgentId: string | null;
    projectId: string | null;
    projectWorkspaceId: string | null;
    executionPolicy: Record<string, unknown> | null;
    executionState: Record<string, unknown> | null;
  } | null,
): Promise<HermesKanbanIssueSeed> {
  const createdAt = task.createdAt ?? task.updatedAt;
  const description = buildHermesKanbanIssueDescription(task);
  const metadata = extractProjectionMetadata(task);
  const assignee = await resolveProjectionAssignee(db, companyId, metadata, task);
  const project = await resolveProjectionProject(db, companyId, metadata, task);
  const warnings = [...metadata.warnings, ...assignee.warnings, ...project.warnings];
  const previousProjection = asRecord(existing?.executionState?.hermesKanbanProjection);
  const previousManagedFields = asRecord(previousProjection?.managedFields) ?? {};
  const assigneeField = preserveManualProjectionField(
    "assigneeAgentId",
    existing?.assigneeAgentId ?? null,
    assignee.agentId,
    previousManagedFields,
    warnings,
  );
  const projectField = preserveManualProjectionField(
    "projectId",
    existing?.projectId ?? null,
    project.projectId,
    previousManagedFields,
    warnings,
  );
  const workspaceField = preserveManualProjectionField(
    "projectWorkspaceId",
    existing?.projectWorkspaceId ?? null,
    project.projectWorkspaceId,
    previousManagedFields,
    warnings,
  );
  const requestedExecutionPolicy = asRecord(metadata.fabric.execution_policy)
    ?? asRecord(metadata.fabric.executionPolicy)
    ?? null;
  const executionPolicyField = preserveManualProjectionField(
    "executionPolicy",
    existing?.executionPolicy ?? null,
    requestedExecutionPolicy,
    previousManagedFields,
    warnings,
  );
  const sourceTrust = toSourceTrustMetadata(metadata.sourceTrust);
  const labelSpecs = deriveProjectionLabels(metadata, task);
  const previousProjectionLabelNames = asStringArray(asRecord(previousManagedFields.labels)?.value)
    .map((name) => name.trim().toLowerCase());
  const managedFields = {
    ...previousManagedFields,
    assigneeAgentId: assigneeField.management,
    projectId: projectField.management,
    projectWorkspaceId: workspaceField.management,
    executionPolicy: executionPolicyField.management,
    labels: {
      owner: "hermes_kanban_projection",
      value: labelSpecs.map((spec) => spec.name),
    },
  };
  const approvalSpecs = await deriveProjectionApprovalRequirements(
    db,
    companyId,
    metadata,
    task,
    assigneeField.value,
  );
  warnings.push(...approvalSpecs.flatMap((spec) => asStringArray(spec.payload.warnings)));
  const executionState = mergeProjectionExecutionState(existing?.executionState ?? null, {
    warnings,
    provenance: metadata.provenance,
    managedFields,
    parents: task.parentTaskIds,
    children: task.childTaskIds,
    taskId: task.id,
    lastSyncAt: task.updatedAt.toISOString(),
  });
  return {
    title: task.title,
    description,
    status: mapHermesKanbanTaskStatus(task.status),
    priority: mapHermesKanbanTaskPriority(task.priority),
    executionAgentNameKey: assignee.nameKey,
    startedAt: task.startedAt,
    completedAt: task.completedAt,
    updatedAt: task.updatedAt,
    createdAt,
    originFingerprint: `hermes-kanban:${task.id}`,
    assigneeAgentId: assigneeField.value,
    projectId: projectField.value,
    projectWorkspaceId: workspaceField.value,
    executionPolicy: executionPolicyField.value,
    executionState,
    sourceTrust,
    labelSpecs,
    previousProjectionLabelNames,
    approvalSpecs,
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
      assigneeAgentId: seed.assigneeAgentId,
      projectId: seed.projectId,
      projectWorkspaceId: seed.projectWorkspaceId,
      executionAgentNameKey: seed.executionAgentNameKey,
      executionPolicy: seed.executionPolicy,
      executionState: seed.executionState,
      sourceTrust: seed.sourceTrust,
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
    assigneeAgentId: string | null;
    projectId: string | null;
    projectWorkspaceId: string | null;
    executionAgentNameKey: string | null;
    executionPolicy: Record<string, unknown> | null;
    executionState: Record<string, unknown> | null;
    sourceTrust: SourceTrustMetadata | null;
    startedAt: Date | null;
    completedAt: Date | null;
    createdAt: Date;
    updatedAt: Date;
    hiddenAt: Date | null;
    originFingerprint: string;
  },
  seed: HermesKanbanIssueSeed,
) {
  const patch: Partial<typeof issues.$inferInsert> = {};
  if (existing.title !== seed.title) patch.title = seed.title;
  if ((existing.description ?? null) !== seed.description) patch.description = seed.description;
  if (existing.status !== seed.status) patch.status = seed.status;
  if (existing.priority !== seed.priority) patch.priority = seed.priority;
  if ((existing.assigneeAgentId ?? null) !== seed.assigneeAgentId) patch.assigneeAgentId = seed.assigneeAgentId;
  if ((existing.projectId ?? null) !== seed.projectId) patch.projectId = seed.projectId;
  if ((existing.projectWorkspaceId ?? null) !== seed.projectWorkspaceId) patch.projectWorkspaceId = seed.projectWorkspaceId;
  if ((existing.executionAgentNameKey ?? null) !== seed.executionAgentNameKey) {
    patch.executionAgentNameKey = seed.executionAgentNameKey;
  }
  if (!jsonEqual(existing.executionPolicy ?? null, seed.executionPolicy)) patch.executionPolicy = seed.executionPolicy;
  if (!jsonEqual(existing.executionState ?? null, seed.executionState)) patch.executionState = seed.executionState;
  if (!jsonEqual(existing.sourceTrust ?? null, seed.sourceTrust)) patch.sourceTrust = seed.sourceTrust;
  if (dateMs(existing.startedAt) !== dateMs(seed.startedAt)) patch.startedAt = seed.startedAt;
  if (dateMs(existing.completedAt) !== dateMs(seed.completedAt)) patch.completedAt = seed.completedAt;
  if (existing.originFingerprint !== seed.originFingerprint) patch.originFingerprint = seed.originFingerprint;
  if (dateMs(existing.createdAt) !== dateMs(seed.createdAt)) patch.createdAt = seed.createdAt;
  if (dateMs(existing.updatedAt) !== dateMs(seed.updatedAt)) patch.updatedAt = seed.updatedAt;
  if (existing.hiddenAt !== null) patch.hiddenAt = null;
  if (Object.keys(patch).length === 0) return false;
  await db.update(issues).set(patch).where(eq(issues.id, issueId));
  return true;
}

async function syncProjectedIssueEnrichment(db: Db, companyId: string, issueId: string, seed: HermesKanbanIssueSeed) {
  const labelsChanged = await syncProjectedIssueLabels(
    db,
    companyId,
    issueId,
    seed.labelSpecs,
    seed.previousProjectionLabelNames,
  );
  const approvalsChanged = await syncProjectedIssueApprovals(db, companyId, issueId, seed.approvalSpecs);
  return labelsChanged || approvalsChanged;
}

async function syncProjectedIssueLabels(
  db: Db,
  companyId: string,
  issueId: string,
  labelSpecs: ProjectionLabelSpec[],
  previousProjectionLabelNames: string[],
) {
  const uniqueSpecs = dedupeLabelSpecs(labelSpecs);
  const names = uniqueSpecs.map((spec) => spec.name);
  let existingLabels = names.length > 0
    ? await db
      .select({ id: labels.id, name: labels.name })
      .from(labels)
      .where(and(eq(labels.companyId, companyId), inArray(labels.name, names)))
    : [];
  const existingNames = new Set(existingLabels.map((label) => label.name));
  const missing = uniqueSpecs.filter((spec) => !existingNames.has(spec.name));
  if (missing.length > 0) {
    await db.insert(labels).values(missing.map((spec) => ({
      companyId,
      name: spec.name,
      color: spec.color,
    }))).onConflictDoNothing();
    existingLabels = await db
      .select({ id: labels.id, name: labels.name })
      .from(labels)
      .where(and(eq(labels.companyId, companyId), inArray(labels.name, names)));
  }

  const existingJoins = await db
    .select({ labelId: issueLabels.labelId, name: labels.name })
    .from(issueLabels)
    .innerJoin(labels, eq(issueLabels.labelId, labels.id))
    .where(and(eq(issueLabels.companyId, companyId), eq(issueLabels.issueId, issueId)));
  const desiredNames = new Set(names);
  const previouslyOwnedNames = new Set(previousProjectionLabelNames.map((name) => name.trim().toLowerCase()));
  const staleOwnedLabelIds = existingJoins
    .filter((row) => previouslyOwnedNames.has(row.name.trim().toLowerCase()) && !desiredNames.has(row.name.trim().toLowerCase()))
    .map((row) => row.labelId);
  let changed = missing.length > 0;
  if (staleOwnedLabelIds.length > 0) {
    await db.delete(issueLabels).where(and(
      eq(issueLabels.companyId, companyId),
      eq(issueLabels.issueId, issueId),
      inArray(issueLabels.labelId, staleOwnedLabelIds),
    ));
    changed = true;
  }
  const joined = new Set(existingJoins.map((row) => row.labelId));
  const joinRows = existingLabels
    .filter((label) => !joined.has(label.id))
    .map((label) => ({ companyId, issueId, labelId: label.id }));
  if (joinRows.length === 0) return changed;
  await db.insert(issueLabels).values(joinRows).onConflictDoNothing();
  return true;
}

async function syncProjectedIssueApprovals(db: Db, companyId: string, issueId: string, approvalSpecs: ProjectionApprovalSpec[]) {
  const existingRows = await db
    .select({ approvalId: approvals.id, type: approvals.type, status: approvals.status, payload: approvals.payload })
    .from(issueApprovals)
    .innerJoin(approvals, eq(issueApprovals.approvalId, approvals.id))
    .where(and(eq(issueApprovals.companyId, companyId), eq(issueApprovals.issueId, issueId)));
  const desiredFingerprints = new Set(approvalSpecs.map((spec) => `${spec.type}:${spec.fingerprint}`));
  const projectionFingerprintKey = (row: { type: string; payload: Record<string, unknown> }) => {
    const payload = asRecord(row.payload);
    const fingerprint = asString(payload?.projectionFingerprint);
    return payload?.source === "hermes_kanban_projection" && fingerprint ? `${row.type}:${fingerprint}` : null;
  };
  const stalePendingProjectionApprovalIds = existingRows
    .filter((row) => row.status === "pending")
    .filter((row) => {
      const key = projectionFingerprintKey(row);
      return key !== null && !desiredFingerprints.has(key);
    })
    .map((row) => row.approvalId);
  let changed = stalePendingProjectionApprovalIds.length > 0;
  if (stalePendingProjectionApprovalIds.length > 0) {
    await db.delete(issueApprovals).where(and(
      eq(issueApprovals.companyId, companyId),
      eq(issueApprovals.issueId, issueId),
      inArray(issueApprovals.approvalId, stalePendingProjectionApprovalIds),
    ));
  }
  const staleIds = new Set(stalePendingProjectionApprovalIds);
  const existingFingerprints = new Set(
    existingRows
      .filter((row) => !staleIds.has(row.approvalId))
      .map((row) => projectionFingerprintKey(row))
      .filter((key): key is string => key !== null),
  );
  for (const spec of approvalSpecs) {
    const fingerprintKey = `${spec.type}:${spec.fingerprint}`;
    if (existingFingerprints.has(fingerprintKey)) continue;
    const [approval] = await db.insert(approvals).values({
      companyId,
      type: spec.type,
      requestedByAgentId: spec.requestedByAgentId,
      status: "pending",
      payload: { ...spec.payload, projectionFingerprint: spec.fingerprint },
    }).returning({ id: approvals.id });
    if (!approval) continue;
    await db.insert(issueApprovals).values({
      companyId,
      issueId,
      approvalId: approval.id,
      linkedByAgentId: spec.requestedByAgentId,
      linkedByUserId: null,
    }).onConflictDoNothing();
    existingFingerprints.add(fingerprintKey);
    changed = true;
  }
  return changed;
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

async function deleteProjectedIssueRelations(db: Db, companyId: string, issueIds: string[]) {
  if (issueIds.length === 0) return false;
  const rows = await db
    .select({ id: issueRelations.id })
    .from(issueRelations)
    .where(
      and(
        eq(issueRelations.companyId, companyId),
        or(inArray(issueRelations.issueId, issueIds), inArray(issueRelations.relatedIssueId, issueIds)),
      ),
    );
  if (rows.length === 0) return false;
  await db.delete(issueRelations).where(
    and(
      eq(issueRelations.companyId, companyId),
      or(inArray(issueRelations.issueId, issueIds), inArray(issueRelations.relatedIssueId, issueIds)),
    ),
  );
  return true;
}

async function hideProjectedIssues(db: Db, issueIds: string[]) {
  if (issueIds.length === 0) return false;
  const rows = await db.select({ id: issues.id }).from(issues).where(and(inArray(issues.id, issueIds), isNull(issues.hiddenAt)));
  if (rows.length === 0) return false;
  const hiddenAt = new Date();
  await db.update(issues)
    .set({ hiddenAt, updatedAt: hiddenAt })
    .where(and(inArray(issues.id, issueIds), isNull(issues.hiddenAt)));
  return true;
}

function extractProjectionMetadata(task: HermesKanbanSnapshotTask): ProjectionMetadata {
  const packets: Array<{ packet: Record<string, unknown>; provenance: string }> = [];
  const runPacket = projectionPacketFromRecord(task.latestRunMetadata);
  if (runPacket) packets.push({ packet: runPacket, provenance: "task_run_metadata" });
  // Events are ordered by id, so later structured events override older
  // events and the latest-run packet field-by-field.
  for (const event of task.events) {
    const eventPacket = projectionPacketFromRecord(event.payload);
    if (eventPacket) packets.push({ packet: eventPacket, provenance: "task_event" });
  }
  if (packets.length === 0) {
    const legacyPacket = extractLegacyHermesAgencyMetadataFromBody(task.body);
    if (legacyPacket) packets.push({ packet: legacyPacket, provenance: "legacy_body_fallback" });
  }

  const fabric: Record<string, unknown> = {};
  const hermesAgency: Record<string, unknown> = {};
  const provenance: string[] = [];
  for (const { packet, provenance: packetProvenance } of packets) {
    mergeProjectionRecord(fabric, asRecord(packet.fabric) ?? {});
    mergeProjectionRecord(hermesAgency, asRecord(packet.hermes_agency) ?? asRecord(packet.hermesAgency) ?? {});
    provenance.push(packetProvenance);
  }
  if (packets.some((entry) => entry.provenance !== "legacy_body_fallback")) provenance.push("structured_metadata");
  if (provenance.length === 0) provenance.push("inference");
  const sourceTrust = asRecord(fabric.source_trust) ?? asRecord(fabric.sourceTrust) ?? null;
  return { fabric, hermesAgency, warnings: [], provenance: [...new Set(provenance)], sourceTrust };
}

function projectionPacketFromRecord(record: Record<string, unknown> | null | undefined) {
  if (!record) return null;
  if (asRecord(record.fabric) || asRecord(record.hermes_agency) || asRecord(record.hermesAgency)) return record;
  const nested = asRecord(record.metadata) ?? asRecord(record.payload);
  if (nested && (asRecord(nested.fabric) || asRecord(nested.hermes_agency) || asRecord(nested.hermesAgency))) return nested;
  return null;
}

function extractLegacyHermesAgencyMetadataFromBody(body: string) {
  const marker = /Hermes Agency metadata\s*:?/i.exec(body);
  if (!marker) return null;
  const section = body.slice(marker.index + marker[0].length, marker.index + marker[0].length + 8_000).trimStart();
  const fenced = /^```(?:json)?\s*\n?([\s\S]*?)```/i.exec(section);
  const jsonText = fenced?.[1]?.trim() ?? extractLeadingJsonObject(section);
  if (!jsonText) return null;
  const parsed = parseJsonObject(jsonText);
  if (!parsed) return null;
  if (asRecord(parsed.fabric) || asRecord(parsed.hermes_agency) || asRecord(parsed.hermesAgency)) return parsed;
  return { hermes_agency: parsed };
}

async function resolveProjectionAssignee(db: Db, companyId: string, metadata: ProjectionMetadata, task: HermesKanbanSnapshotTask) {
  const requestedAgentId = asString(metadata.fabric.assignee_agent_id) ?? asString(metadata.fabric.assigneeAgentId);
  const warnings: string[] = [];
  if (requestedAgentId && isUuid(requestedAgentId)) {
    const [agent] = await db.select({ id: agents.id, name: agents.name, metadata: agents.metadata })
      .from(agents)
      .where(and(eq(agents.companyId, companyId), eq(agents.id, requestedAgentId)))
      .limit(1);
    if (agent) {
      return {
        agentId: agent.id,
        nameKey: asString(asRecord(agent.metadata)?.name_key) ?? asString(asRecord(agent.metadata)?.nameKey) ?? agent.name,
        warnings,
      };
    }
    warnings.push(`Hermes assignee agent id ${requestedAgentId} is not in company ${companyId}; trying profile resolution.`);
  } else if (requestedAgentId) {
    warnings.push(`Hermes assignee agent id ${requestedAgentId} is invalid; trying profile resolution.`);
  }
  const candidate = firstString([
    metadata.fabric.assignee_agent_name_key,
    metadata.fabric.assigneeAgentNameKey,
    metadata.hermesAgency.assignee_profile,
    metadata.hermesAgency.execution_agent_name_key,
    metadata.hermesAgency.target_profile,
    metadata.hermesAgency.target_agent,
    task.assignee,
  ]);
  if (!candidate) return { agentId: null, nameKey: null, warnings };
  const resolved = await resolveAgentNameKey(db, companyId, candidate);
  if (resolved.agentId) return { agentId: resolved.agentId, nameKey: candidate, warnings };
  warnings.push(resolved.warning ?? `Unknown Hermes assignee profile ${candidate}; assigneeAgentId left unresolved.`);
  return { agentId: null, nameKey: candidate, warnings };
}

async function resolveProjectionProject(db: Db, companyId: string, metadata: ProjectionMetadata, task: HermesKanbanSnapshotTask) {
  const projectRecord = asRecord(metadata.fabric.project);
  const requestedProjectId = asString(projectRecord?.id) ?? asString(metadata.fabric.project_id) ?? asString(metadata.fabric.projectId);
  const projectName = firstString([projectRecord?.key, projectRecord?.name, metadata.fabric.project_key, metadata.fabric.projectName]);
  const workspacePath = firstString([projectRecord?.workspace_path, projectRecord?.workspacePath, task.workspacePath]);
  const warnings: string[] = [];
  if (requestedProjectId && isUuid(requestedProjectId)) {
    const [project] = await db.select({ id: projects.id }).from(projects)
      .where(and(eq(projects.companyId, companyId), eq(projects.id, requestedProjectId))).limit(1);
    if (project) {
      const projectWorkspaceId = await resolveProjectWorkspaceId(db, companyId, project.id, workspacePath);
      return { projectId: project.id, projectWorkspaceId, warnings };
    }
    warnings.push(`Hermes project id ${requestedProjectId} is not in company ${companyId}; trying project hints.`);
  } else if (requestedProjectId) {
    warnings.push(`Hermes project id ${requestedProjectId} is invalid; trying project hints.`);
  }
  const projectRows = await db.select({ id: projects.id, name: projects.name }).from(projects).where(eq(projects.companyId, companyId));
  const normalizedProjectName = normalizeNameKey(projectName);
  const matchedProjects = projectName
    ? projectRows.filter((row) => row.name === projectName || normalizeNameKey(row.name) === normalizedProjectName)
    : [];
  if (matchedProjects.length === 1) {
    const matchedProject = matchedProjects[0]!;
    const projectWorkspaceId = await resolveProjectWorkspaceId(db, companyId, matchedProject.id, workspacePath);
    return { projectId: matchedProject.id, projectWorkspaceId, warnings };
  }
  if (matchedProjects.length > 1) {
    warnings.push(`Hermes project hint ${projectName} matched multiple company projects; projectId left unresolved.`);
    return { projectId: null, projectWorkspaceId: null, warnings };
  }
  if (workspacePath) {
    const workspaceRows = await db.select({ id: projectWorkspaces.id, projectId: projectWorkspaces.projectId })
      .from(projectWorkspaces)
      .where(and(eq(projectWorkspaces.companyId, companyId), eq(projectWorkspaces.cwd, workspacePath)));
    if (workspaceRows.length === 1) {
      const workspace = workspaceRows[0]!;
      return { projectId: workspace.projectId, projectWorkspaceId: workspace.id, warnings };
    }
    if (workspaceRows.length > 1) {
      warnings.push(`Hermes workspace ${workspacePath} matched multiple company projects; projectId left unresolved.`);
      return { projectId: null, projectWorkspaceId: null, warnings };
    }
  }
  if (requestedProjectId || projectName || workspacePath) {
    warnings.push(`Unknown Hermes project ${requestedProjectId ?? projectName ?? workspacePath}; projectId left unresolved.`);
  }
  return { projectId: null, projectWorkspaceId: null, warnings };
}

async function resolveProjectWorkspaceId(db: Db, companyId: string, projectId: string, workspacePath: string | null) {
  if (!workspacePath) return null;
  const [workspace] = await db.select({ id: projectWorkspaces.id }).from(projectWorkspaces)
    .where(and(eq(projectWorkspaces.companyId, companyId), eq(projectWorkspaces.projectId, projectId), eq(projectWorkspaces.cwd, workspacePath)))
    .limit(1);
  return workspace?.id ?? null;
}

async function resolveAgentNameKey(db: Db, companyId: string, nameKey: string) {
  const rows = await db.select({ id: agents.id, name: agents.name, metadata: agents.metadata }).from(agents).where(eq(agents.companyId, companyId));
  const normalized = normalizeNameKey(nameKey);
  const matched = rows.filter((row) => {
    const metadata = asRecord(row.metadata);
    return row.name === nameKey ||
      normalizeNameKey(row.name) === normalized ||
      normalizeNameKey(asString(metadata?.name_key) ?? asString(metadata?.nameKey)) === normalized;
  });
  if (matched.length === 1) return { agentId: matched[0]!.id, warning: null };
  if (matched.length > 1) {
    return { agentId: null, warning: `Hermes profile ${nameKey} matched multiple company agents; value left unresolved.` };
  }
  return { agentId: null, warning: `Unknown Hermes profile ${nameKey}; value left unresolved.` };
}

function deriveProjectionLabels(metadata: ProjectionMetadata, task: HermesKanbanSnapshotTask): ProjectionLabelSpec[] {
  const specs: ProjectionLabelSpec[] = [{ name: "kanban", color: "#64748b" }];
  const labelRecords = Array.isArray(metadata.fabric.labels) ? metadata.fabric.labels : [];
  for (const label of labelRecords) {
    const record = asRecord(label);
    const name = asString(record?.name) ?? (typeof label === "string" ? label : null);
    if (name && isValidProjectionLabelName(name)) {
      specs.push({ name: name.toLowerCase(), color: normalizeProjectionLabelColor(asString(record?.color)) });
    }
  }
  if (task.status === "blocked") specs.push({ name: "blocked", color: "#ef4444" });
  if (task.status === "in_review") specs.push({ name: "in-review", color: "#a855f7" });
  const assigneeHint = firstString([
    metadata.hermesAgency.assignee_profile,
    metadata.hermesAgency.target_profile,
    metadata.hermesAgency.execution_agent_name_key,
    task.assignee,
  ]) ?? "";
  const skills = asStringArray(metadata.hermesAgency.requested_skills);
  const haystack = `${assigneeHint} ${skills.join(" ")}`.toLowerCase();
  if (/review|code-review/.test(haystack)) specs.push({ name: "review", color: "#a855f7" });
  if (/frontend|react|ui/.test(haystack)) specs.push({ name: "frontend", color: "#38bdf8" });
  if (/backend|api|server/.test(haystack)) specs.push({ name: "backend", color: "#22c55e" });
  const policy = asRecord(metadata.fabric.approval_policy) ?? {};
  if (policy.requires_security_review || /security|auth|secret/.test(haystack)) specs.push({ name: "security", color: "#f97316" });
  if (policy.requires_deploy_approval || /deploy|production/.test(haystack)) specs.push({ name: "deploy", color: "#eab308" });
  if (policy.destructive) specs.push({ name: "destructive", color: "#dc2626" });
  const labelIntents = asRecord(metadata.fabric.label_intents) ?? asRecord(metadata.fabric.labelIntents);
  const addedNames = asStringArray(labelIntents?.add)
    .map((name) => name.trim().toLowerCase())
    .filter(isAllowedFabricSyncLabelName);
  for (const name of addedNames) specs.push({ name, color: "#64748b" });
  const removedNames = new Set(
    asStringArray(labelIntents?.removal_intent ?? labelIntents?.removalIntent)
      .map((name) => name.trim().toLowerCase())
      .filter(isAllowedFabricSyncLabelName),
  );
  return dedupeLabelSpecs(specs).filter((spec) => !removedNames.has(spec.name));
}

async function deriveProjectionApprovalRequirements(
  db: Db,
  companyId: string,
  metadata: ProjectionMetadata,
  task: HermesKanbanSnapshotTask,
  assigneeAgentId: string | null,
): Promise<ProjectionApprovalSpec[]> {
  const specs: ProjectionApprovalSpec[] = [];
  for (const reviewer of Array.isArray(metadata.fabric.reviewers) ? metadata.fabric.reviewers : []) {
    const record = asRecord(reviewer);
    const nameKey = firstString([record?.agent_name_key, record?.agentNameKey, record?.profile, record?.name]);
    if (!nameKey) continue;
    const resolved = await resolveAgentNameKey(db, companyId, nameKey);
    specs.push({
      type: "review_required",
      requestedByAgentId: assigneeAgentId,
      fingerprint: stableProjectionFingerprint("review_required", task.id, nameKey),
      payload: {
        source: "hermes_kanban_projection",
        reviewerAgentNameKey: nameKey,
        reviewerAgentId: resolved.agentId,
        required: record?.required ?? true,
        reason: asString(record?.reason),
        warnings: resolved.agentId ? [] : [`Unknown reviewer profile ${nameKey}; approval requirement left unresolved.`],
      },
    });
  }
  for (const approver of Array.isArray(metadata.fabric.approvers) ? metadata.fabric.approvers : []) {
    const record = asRecord(approver);
    const nameKey = firstString([record?.agent_name_key, record?.agentNameKey, record?.profile, record?.name]);
    if (!nameKey) continue;
    const resolved = await resolveAgentNameKey(db, companyId, nameKey);
    specs.push({
      type: "approval_required",
      requestedByAgentId: assigneeAgentId,
      fingerprint: stableProjectionFingerprint("approval_required", task.id, nameKey),
      payload: {
        source: "hermes_kanban_projection",
        approverAgentNameKey: nameKey,
        approverAgentId: resolved.agentId,
        required: record?.required ?? true,
        reason: asString(record?.reason),
        warnings: resolved.agentId ? [] : [`Unknown approver profile ${nameKey}; approval requirement left unresolved.`],
      },
    });
  }
  const policy = asRecord(metadata.fabric.approval_policy) ?? asRecord(metadata.fabric.approvalPolicy) ?? {};
  if (policy.requires_security_review === true || policy.requiresSecurityReview === true || policy.destructive === true) {
    const securityReviewer = "agency-security-reviewer";
    const resolved = await resolveAgentNameKey(db, companyId, securityReviewer);
    specs.push({
      type: "review_required",
      requestedByAgentId: assigneeAgentId,
      fingerprint: stableProjectionFingerprint("review_required", task.id, securityReviewer),
      payload: {
        source: "hermes_kanban_projection",
        reviewerAgentNameKey: securityReviewer,
        reviewerAgentId: resolved.agentId,
        required: true,
        reason: policy.destructive === true ? "destructive" : "security_sensitive",
        warnings: resolved.agentId ? [] : [resolved.warning],
      },
    });
  }
  if (policy.requires_deploy_approval === true || policy.requiresDeployApproval === true) {
    specs.push(humanApprovalSpec(task.id, "deploy", assigneeAgentId));
  }
  if (policy.requires_human === true || policy.requiresHuman === true) {
    specs.push(humanApprovalSpec(task.id, "human", assigneeAgentId));
  }
  return dedupeApprovalSpecs(specs);
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
    task.lastHeartbeatAt ? `Last heartbeat: ${task.lastHeartbeatAt.toISOString()}` : null,
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function preserveManualProjectionField<T>(
  field: string,
  currentValue: T | null,
  requestedValue: T | null,
  previousManagedFields: Record<string, unknown>,
  warnings: string[],
) {
  const previousManagement = asRecord(previousManagedFields[field]);
  const projectionOwned = previousManagement?.owner === "hermes_kanban_projection"
    && jsonEqual(previousManagement.value ?? null, currentValue);
  const reverseSyncOwned = previousManagement?.owner === "fabric_manual_override"
    || previousManagement?.owner === "fabric_pending_reverse_sync";
  if ((currentValue !== null || reverseSyncOwned) && !jsonEqual(currentValue, requestedValue) && (!projectionOwned || reverseSyncOwned)) {
    warnings.push(`Preserved manual ${projectionFieldDisplayName(field)}; projection requested a different value.`);
    return {
      value: currentValue,
      management: reverseSyncOwned
        ? previousManagement
        : { owner: "fabric_manual_override", value: currentValue },
    };
  }
  return {
    value: requestedValue,
    management: { owner: "hermes_kanban_projection", value: requestedValue },
  };
}

function projectionFieldDisplayName(field: string) {
  if (field === "assigneeAgentId") return "assignee";
  if (field === "projectId") return "project";
  if (field === "projectWorkspaceId") return "project workspace";
  if (field === "executionPolicy") return "execution policy";
  return field;
}

function mergeProjectionRecord(target: Record<string, unknown>, source: Record<string, unknown>) {
  for (const [key, value] of Object.entries(source)) {
    const targetRecord = asRecord(target[key]);
    const sourceRecord = asRecord(value);
    if (targetRecord && sourceRecord) mergeProjectionRecord(targetRecord, sourceRecord);
    else target[key] = value;
  }
}

function extractLeadingJsonObject(value: string) {
  const start = value.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (let index = start; index < value.length; index += 1) {
    const char = value[index];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') quoted = false;
      continue;
    }
    if (char === '"') quoted = true;
    else if (char === "{") depth += 1;
    else if (char === "}" && --depth === 0) return value.slice(start, index + 1);
  }
  return null;
}

function asString(value: unknown) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => asString(item)).filter((item): item is string => Boolean(item)) : [];
}

function firstString(values: unknown[]) {
  for (const value of values) {
    const stringValue = asString(value);
    if (stringValue) return stringValue;
  }
  return null;
}

function normalizeNameKey(value: string | null | undefined) {
  return (value ?? "").trim().toLowerCase().replace(/[_\s]+/g, "-");
}

function isUuid(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isValidProjectionLabelName(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= 100 && !/[\u0000-\u001f\u007f]/.test(trimmed);
}

function isAllowedFabricSyncLabelName(value: string) {
  return /^(?:hermes|risk|skill|routing):/i.test(value) && isValidProjectionLabelName(value);
}

function normalizeProjectionLabelColor(value: string | null) {
  return value && /^#[0-9a-f]{6}$/i.test(value) ? value : "#64748b";
}

function dedupeLabelSpecs(specs: ProjectionLabelSpec[]) {
  const byName = new Map<string, ProjectionLabelSpec>();
  for (const spec of specs) {
    const name = spec.name.trim().toLowerCase();
    if (!name || byName.has(name)) continue;
    byName.set(name, { name, color: spec.color || "#64748b" });
  }
  return [...byName.values()];
}

function dedupeApprovalSpecs(specs: ProjectionApprovalSpec[]) {
  const byFingerprint = new Map<string, ProjectionApprovalSpec>();
  for (const spec of specs) {
    const key = `${spec.type}:${spec.fingerprint}`;
    if (!byFingerprint.has(key)) byFingerprint.set(key, spec);
  }
  return [...byFingerprint.values()];
}

function humanApprovalSpec(taskId: string, reason: string, requestedByAgentId: string | null): ProjectionApprovalSpec {
  return {
    type: "approval_required",
    requestedByAgentId,
    fingerprint: stableProjectionFingerprint("approval_required", taskId, `human:${reason}`),
    payload: {
      source: "hermes_kanban_projection",
      required: true,
      requiresHuman: true,
      reason,
      warnings: [],
    },
  };
}

function jsonEqual(left: unknown, right: unknown) {
  return stableJsonStringify(left ?? null) === stableJsonStringify(right ?? null);
}

function stableJsonStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => stableJsonStringify(item)).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableJsonStringify(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function toSourceTrustMetadata(value: Record<string, unknown> | null): SourceTrustMetadata {
  const trustLevel = asString(value?.trust_level) ?? asString(value?.trustLevel);
  const preset = value?.preset === "low_trust_review" || trustLevel === "external" || trustLevel === "untrusted"
    ? "low_trust_review"
    : "standard";
  const disposition = value?.disposition === "quarantined" || preset === "low_trust_review"
    ? "quarantined"
    : "promoted";
  return { preset, disposition };
}

function mergeProjectionExecutionState(existing: Record<string, unknown> | null, projection: Record<string, unknown>) {
  const previousProjection = asRecord(existing?.hermesKanbanProjection) ?? {};
  return {
    ...(existing ?? {}),
    hermesKanbanProjection: {
      ...previousProjection,
      ...projection,
    },
  };
}

function stableProjectionFingerprint(type: string, taskId: string, subject: string) {
  return `${type}:${taskId}:${normalizeNameKey(subject)}`;
}

/**
 * From all existing projected rows, pick the best row per originId:
 * prefer unhidden over hidden; among same hidden-state, prefer most recently updated,
 * then the lower issue number as a deterministic creation-order tie-breaker.
 */
function deduplicateExistingRows<T extends {
  originId: string | null;
  hiddenAt: Date | null;
  updatedAt: Date;
  issueNumber: number | null;
}>(
  rows: Array<T>,
): Array<T> {
  const best = new Map<string, T>();
  for (const row of rows) {
    const key = row.originId ?? "";
    if (!key) continue;
    const current = best.get(key);
    if (!current) {
      best.set(key, row);
      continue;
    }
    // Prefer unhidden over hidden
    const rowHidden = row.hiddenAt !== null;
    const currentHidden = current.hiddenAt !== null;
    if (rowHidden !== currentHidden) {
      best.set(key, rowHidden ? current : row);
      continue;
    }
    // Same hidden-state: prefer most recently updated
    const rowTime = row.updatedAt?.getTime() ?? 0;
    const currentTime = current.updatedAt?.getTime() ?? 0;
    const rowIssueNumber = row.issueNumber ?? Number.MAX_SAFE_INTEGER;
    const currentIssueNumber = current.issueNumber ?? Number.MAX_SAFE_INTEGER;
    if (rowTime > currentTime || (rowTime === currentTime && rowIssueNumber < currentIssueNumber)) best.set(key, row);
  }
  return [...best.values()];
}

/**
 * Find IDs of unhidden duplicate rows that were NOT selected as the canonical row
 * for their originId. These are sync races that should be hidden.
 */
function findDuplicateUnhiddenIds(
  allRows: Array<{ id: string; originId: string | null; hiddenAt: Date | null }>,
  canonicalByTaskId: Map<string, { id: string }>,
): string[] {
  const canonicalIds = new Set([...canonicalByTaskId.values()].map((r) => r.id));
  return allRows
    .filter((row) => row.originId && row.hiddenAt === null && !canonicalIds.has(row.id))
    .map((row) => row.id);
}
