import { accessSync, constants, existsSync } from "node:fs";
import { homedir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { and, eq, inArray, isNull, or, sql } from "drizzle-orm";
import type { Db } from "@paperclipai/db";
import { companies, issueRelations, issues } from "@paperclipai/db";
import { logger } from "../middleware/logger.js";
import { fabricEnv } from "../fabric-env.js";

export const HERMES_KANBAN_TASK_ORIGIN_KIND = "hermes_kanban_task";
const HERMES_KANBAN_SYNC_HEADER = "X-Hermes-Kanban-Sync";
const HERMES_KANBAN_SYNC_MESSAGE_HEADER = "X-Hermes-Kanban-Sync-Message";
const HERMES_KANBAN_SYNC_DEFAULT_INTERVAL_MS = 15_000;
const HERMES_KANBAN_SYNC_MIN_INTERVAL_MS = 1_000;
const HERMES_KANBAN_SYNC_MAX_BACKOFF_MS = 60_000;

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
    // Deduplicate: prefer unhidden rows; among same hidden-state, prefer most recently updated.
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
  if ((existing.executionAgentNameKey ?? null) !== seed.executionAgentNameKey) {
    patch.executionAgentNameKey = seed.executionAgentNameKey;
  }
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

function asString(value: unknown) {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

/**
 * From all existing projected rows, pick the best row per originId:
 * prefer unhidden over hidden; among same hidden-state, prefer most recently updated.
 */
function deduplicateExistingRows<T extends { originId: string | null; hiddenAt: Date | null; updatedAt: Date }>(
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
    if (rowTime > currentTime) best.set(key, row);
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
