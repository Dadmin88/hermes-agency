import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import express from "express";
import request from "supertest";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { and, eq, isNull, sql } from "drizzle-orm";
import { companies, createDb, issueRelations, issues } from "@paperclipai/db";
import {
  getEmbeddedPostgresTestSupport,
  startEmbeddedPostgresTestDatabase,
} from "./helpers/embedded-postgres.js";
import {
  createHermesKanbanProjectionSyncWorker,
  HERMES_KANBAN_TASK_ORIGIN_KIND,
  resolveHermesKanbanDbPath,
  resolveHermesKanbanSyncIntervalMs,
  syncHermesKanbanIssues,
} from "../services/hermes-kanban-issues.ts";
import { hermesAgencyRoutes } from "../routes/hermes-agency.ts";
import { issueRoutes } from "../routes/issues.ts";
import { errorHandler } from "../middleware/error-handler.ts";
import { issueService } from "../services/issues.ts";

const embeddedPostgresSupport = await getEmbeddedPostgresTestSupport();
const describeEmbeddedPostgres = embeddedPostgresSupport.supported ? describe : describe.skip;

describe("resolveHermesKanbanDbPath", () => {
  const previousFabric = process.env.FABRIC_HERMES_KANBAN_DB;
  const previousLegacy = process.env.PAPERCLIP_HERMES_KANBAN_DB;
  const previousUnprefixed = process.env.HERMES_KANBAN_DB;

  afterEach(() => {
    if (previousFabric === undefined) delete process.env.FABRIC_HERMES_KANBAN_DB;
    else process.env.FABRIC_HERMES_KANBAN_DB = previousFabric;
    if (previousLegacy === undefined) delete process.env.PAPERCLIP_HERMES_KANBAN_DB;
    else process.env.PAPERCLIP_HERMES_KANBAN_DB = previousLegacy;
    if (previousUnprefixed === undefined) delete process.env.HERMES_KANBAN_DB;
    else process.env.HERMES_KANBAN_DB = previousUnprefixed;
  });

  it("prefers FABRIC_HERMES_KANBAN_DB when set", () => {
    process.env.FABRIC_HERMES_KANBAN_DB = "/tmp/fabric-kanban.db";
    expect(resolveHermesKanbanDbPath()).toBe("/tmp/fabric-kanban.db");
  });

  it("does not fall back to the default home-directory Hermes Kanban DB", () => {
    delete process.env.FABRIC_HERMES_KANBAN_DB;
    delete process.env.PAPERCLIP_HERMES_KANBAN_DB;
    delete process.env.HERMES_KANBAN_DB;
    expect(resolveHermesKanbanDbPath()).toBeNull();
  });
});

describe("resolveHermesKanbanSyncIntervalMs", () => {
  const previousFabric = process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS;
  const previousLegacy = process.env.PAPERCLIP_HERMES_KANBAN_SYNC_INTERVAL_MS;
  const previousUnprefixed = process.env.HERMES_KANBAN_SYNC_INTERVAL_MS;

  afterEach(() => {
    if (previousFabric === undefined) delete process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS;
    else process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS = previousFabric;
    if (previousLegacy === undefined) delete process.env.PAPERCLIP_HERMES_KANBAN_SYNC_INTERVAL_MS;
    else process.env.PAPERCLIP_HERMES_KANBAN_SYNC_INTERVAL_MS = previousLegacy;
    if (previousUnprefixed === undefined) delete process.env.HERMES_KANBAN_SYNC_INTERVAL_MS;
    else process.env.HERMES_KANBAN_SYNC_INTERVAL_MS = previousUnprefixed;
  });

  it("defaults to a 15 second Kanban projection sync interval", () => {
    delete process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS;
    delete process.env.PAPERCLIP_HERMES_KANBAN_SYNC_INTERVAL_MS;
    delete process.env.HERMES_KANBAN_SYNC_INTERVAL_MS;
    expect(resolveHermesKanbanSyncIntervalMs()).toBe(15_000);
  });

  it("uses a configured interval with a safe lower bound", () => {
    process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS = "250";
    expect(resolveHermesKanbanSyncIntervalMs()).toBe(1_000);
    process.env.FABRIC_HERMES_KANBAN_SYNC_INTERVAL_MS = "20000";
    expect(resolveHermesKanbanSyncIntervalMs()).toBe(20_000);
  });
});

async function ensureIssueRelationsTable(db: ReturnType<typeof createDb>) {
  await db.execute(sql.raw(`
    CREATE TABLE IF NOT EXISTS "issue_relations" (
      "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      "company_id" uuid NOT NULL,
      "issue_id" uuid NOT NULL,
      "related_issue_id" uuid NOT NULL,
      "type" text NOT NULL,
      "created_by_agent_id" uuid,
      "created_by_user_id" text,
      "created_at" timestamptz NOT NULL DEFAULT now(),
      "updated_at" timestamptz NOT NULL DEFAULT now()
    );
  `));
}

function seedKanbanDb(rows: {
  tasks: Array<{
    id: string;
    title: string;
    body?: string;
    assignee?: string | null;
    status: string;
    priority: number;
    workspacePath?: string | null;
    createdAt: number;
    startedAt?: number | null;
    completedAt?: number | null;
    lastHeartbeatAt?: number | null;
    result?: string | null;
    blockKind?: string | null;
  }>;
  links?: Array<{ parentId: string; childId: string }>;
  taskRuns?: Array<{
    taskId: string;
    summary?: string | null;
    error?: string | null;
    lastHeartbeatAt?: number | null;
    endedAt?: number | null;
  }>;
  taskEvents?: Array<{ taskId: string; kind: string; payload?: Record<string, unknown> | null }>;
}) {
  const dir = mkdtempSync(join(tmpdir(), "fabric-kanban-sync-"));
  const dbPath = join(dir, "kanban.db");
  const sqlite = new DatabaseSync(dbPath);
  sqlite.exec(`
    CREATE TABLE tasks (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      body TEXT DEFAULT '',
      assignee TEXT,
      status TEXT NOT NULL,
      priority INTEGER DEFAULT 0,
      tenant TEXT,
      workspace_path TEXT,
      created_at INTEGER,
      started_at INTEGER,
      completed_at INTEGER,
      result TEXT,
      last_heartbeat_at INTEGER,
      block_kind TEXT
    );
    CREATE TABLE task_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      summary TEXT,
      error TEXT,
      last_heartbeat_at INTEGER,
      ended_at INTEGER,
      metadata TEXT
    );
    CREATE TABLE task_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      payload TEXT
    );
    CREATE TABLE task_links (
      parent_id TEXT NOT NULL,
      child_id TEXT NOT NULL
    );
  `);

  writeKanbanSnapshot(sqlite, rows);
  sqlite.close();
  return { dir, dbPath };
}

function overwriteKanbanDb(dbPath: string, rows: Parameters<typeof seedKanbanDb>[0]) {
  const sqlite = new DatabaseSync(dbPath);
  sqlite.exec(`
    DELETE FROM task_links;
    DELETE FROM task_events;
    DELETE FROM task_runs;
    DELETE FROM tasks;
  `);
  writeKanbanSnapshot(sqlite, rows);
  sqlite.close();
}

function writeKanbanSnapshot(sqlite: DatabaseSync, rows: Parameters<typeof seedKanbanDb>[0]) {
  const insertTask = sqlite.prepare(`
    INSERT INTO tasks (
      id, title, body, assignee, status, priority, tenant, workspace_path,
      created_at, started_at, completed_at, result, last_heartbeat_at, block_kind
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  for (const task of rows.tasks) {
    insertTask.run(
      task.id,
      task.title,
      task.body ?? "",
      task.assignee ?? null,
      task.status,
      task.priority,
      null,
      task.workspacePath ?? null,
      task.createdAt,
      task.startedAt ?? null,
      task.completedAt ?? null,
      task.result ?? null,
      task.lastHeartbeatAt ?? null,
      task.blockKind ?? null,
    );
  }

  const insertRun = sqlite.prepare(`
    INSERT INTO task_runs (task_id, summary, error, last_heartbeat_at, ended_at, metadata)
    VALUES (?, ?, ?, ?, ?, ?)
  `);
  for (const run of rows.taskRuns ?? []) {
    insertRun.run(
      run.taskId,
      run.summary ?? null,
      run.error ?? null,
      run.lastHeartbeatAt ?? null,
      run.endedAt ?? null,
      null,
    );
  }

  const insertEvent = sqlite.prepare(`
    INSERT INTO task_events (task_id, kind, payload) VALUES (?, ?, ?)
  `);
  for (const event of rows.taskEvents ?? []) {
    insertEvent.run(event.taskId, event.kind, event.payload ? JSON.stringify(event.payload) : null);
  }

  const insertLink = sqlite.prepare(`INSERT INTO task_links (parent_id, child_id) VALUES (?, ?)`);
  for (const link of rows.links ?? []) {
    insertLink.run(link.parentId, link.childId);
  }
}

if (!embeddedPostgresSupport.supported) {
  console.warn(
    `Skipping Hermes Kanban issue sync tests on this host: ${embeddedPostgresSupport.reason ?? "unsupported environment"}`,
  );
}

describeEmbeddedPostgres("syncHermesKanbanIssues", () => {
  let db!: ReturnType<typeof createDb>;
  let svc!: ReturnType<typeof issueService>;
  let tempDb: Awaited<ReturnType<typeof startEmbeddedPostgresTestDatabase>> | null = null;
  let previousDbEnv: string | undefined;
  let previousCompanyEnv: string | undefined;
  let previousLegacyCompanyEnv: string | undefined;
  let previousIncludeDetailsEnv: string | undefined;
  let previousRosterPathEnv: string | undefined;
  const tempDirs: string[] = [];

  beforeAll(async () => {
    tempDb = await startEmbeddedPostgresTestDatabase("paperclip-hermes-kanban-sync-");
    db = createDb(tempDb.connectionString);
    svc = issueService(db);
    await ensureIssueRelationsTable(db);
  }, 20_000);

  beforeEach(() => {
    previousDbEnv = process.env.FABRIC_HERMES_KANBAN_DB;
    previousCompanyEnv = process.env.FABRIC_HERMES_KANBAN_COMPANY_ID;
    previousLegacyCompanyEnv = process.env.PAPERCLIP_HERMES_KANBAN_COMPANY_ID;
    previousIncludeDetailsEnv = process.env.FABRIC_HERMES_KANBAN_INCLUDE_DETAILS;
    previousRosterPathEnv = process.env.HERMES_AGENCY_ROSTER_PATH;
  });

  afterEach(async () => {
    if (previousDbEnv === undefined) delete process.env.FABRIC_HERMES_KANBAN_DB;
    else process.env.FABRIC_HERMES_KANBAN_DB = previousDbEnv;
    if (previousCompanyEnv === undefined) delete process.env.FABRIC_HERMES_KANBAN_COMPANY_ID;
    else process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = previousCompanyEnv;
    if (previousLegacyCompanyEnv === undefined) delete process.env.PAPERCLIP_HERMES_KANBAN_COMPANY_ID;
    else process.env.PAPERCLIP_HERMES_KANBAN_COMPANY_ID = previousLegacyCompanyEnv;
    if (previousIncludeDetailsEnv === undefined) delete process.env.FABRIC_HERMES_KANBAN_INCLUDE_DETAILS;
    else process.env.FABRIC_HERMES_KANBAN_INCLUDE_DETAILS = previousIncludeDetailsEnv;
    if (previousRosterPathEnv === undefined) delete process.env.HERMES_AGENCY_ROSTER_PATH;
    else process.env.HERMES_AGENCY_ROSTER_PATH = previousRosterPathEnv;
    await db.delete(issueRelations);
    await db.delete(issues);
    await db.delete(companies);
    while (tempDirs.length > 0) {
      rmSync(tempDirs.pop()!, { recursive: true, force: true });
    }
  });

  afterAll(async () => {
    await tempDb?.cleanup();
  });

  async function seedCompany(name = "Fabric") {
    const companyId = randomUUID();
    await db.insert(companies).values({
      id: companyId,
      name,
      issuePrefix: `FK${companyId.replace(/-/g, "").slice(0, 4).toUpperCase()}`,
      issueCounter: 0,
      requireBoardApprovalForNewAgents: false,
    });
    return companyId;
  }

  it("syncs Hermes Kanban tasks into the issue list with status mapping and native issue coexistence", async () => {
    const companyId = await seedCompany();
    await svc.create(companyId, {
      title: "Existing native issue",
      description: "native",
      status: "todo",
      priority: "medium",
      originKind: "manual",
    });

    const createdAt = 1_782_827_060;
    const { dir, dbPath } = seedKanbanDb({
      tasks: [
        {
          id: "t_parent",
          title: "Projected parent task",
          body: "Parent body",
          assignee: "agency-fullstack-engineer",
          status: "running",
          priority: 98,
          workspacePath: "/tmp/projected-parent",
          createdAt,
          startedAt: createdAt + 10,
          lastHeartbeatAt: createdAt + 50,
        },
        {
          id: "t_child",
          title: "Projected child task",
          body: "Child body",
          status: "blocked",
          priority: 45,
          createdAt,
          blockKind: "needs_input",
        },
      ],
      links: [{ parentId: "t_parent", childId: "t_child" }],
      taskRuns: [{ taskId: "t_parent", summary: "Latest run summary", lastHeartbeatAt: createdAt + 50 }],
      taskEvents: [{ taskId: "t_child", kind: "blocked", payload: { reason: "Waiting for review" } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const sync = await syncHermesKanbanIssues(db, companyId);
    expect(sync.status).toBe("ok");
    expect(sync.projectedCount).toBe(2);
    expect(sync.syncedCount).toBeGreaterThanOrEqual(2);

    const issueList = await svc.list(companyId, { includeBlockedBy: true, includeRoutineExecutions: true });
    expect(issueList.map((issue) => issue.title)).toEqual(expect.arrayContaining([
      "Existing native issue",
      "Projected parent task",
      "Projected child task",
    ]));

    const projectedParent = issueList.find((issue) => issue.title === "Projected parent task");
    const projectedChild = issueList.find((issue) => issue.title === "Projected child task");
    expect(projectedParent?.status).toBe("in_progress");
    expect(projectedChild?.status).toBe("blocked");
    expect(projectedParent?.priority).toBe("critical");
    expect(projectedChild?.priority).toBe("medium");
    expect(projectedParent?.executionAgentNameKey).toBe("agency-fullstack-engineer");
    expect(projectedParent?.description).toContain("Hermes Kanban task: t_parent");
    expect(projectedParent?.description).toContain("Assignee: agency-fullstack-engineer");
    expect(projectedParent?.description).toContain("Last heartbeat: 2026-06-30T13:45:10.000Z");
    expect(projectedParent?.description).not.toContain("Parent body");
    expect(projectedParent?.description).not.toContain("/tmp/projected-parent");
    expect(projectedParent?.description).not.toContain("Latest run summary");
    expect(projectedChild?.description).not.toContain("Waiting for review");
    expect(projectedChild?.blockedBy?.map((entry) => entry.title)).toEqual(["Projected parent task"]);

    const projectedRows = await db
      .select({ originId: issues.originId, originKind: issues.originKind })
      .from(issues)
      .where(eq(issues.companyId, companyId));
    expect(projectedRows.filter((row) => row.originKind === HERMES_KANBAN_TASK_ORIGIN_KIND)).toHaveLength(2);
  });

  it("joins Agency roster health onto projected task assignees in the issue list API", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_roster_health",
        title: "Projected task with Agency assignee",
        assignee: "agency-backend-engineer",
        status: "running",
        priority: 95,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    const rosterPath = join(dir, "roster_state.json");
    writeFileSync(rosterPath, JSON.stringify({
      profiles: [{
        name: "agency-backend-engineer",
        category: "engineering",
        skills: ["api", "server"],
        online: false,
        last_seen: "2026-07-10T02:00:00.000Z",
        peer_id: "12D3KooWDoNotExposeByDefault",
        disabled: false,
      }],
    }));
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    process.env.HERMES_AGENCY_ROSTER_PATH = rosterPath;

    const app = express();
    app.use(express.json());
    app.use((req, _res, next) => {
      (req as any).actor = {
        type: "board",
        source: "local_implicit",
        userId: "board-user",
        isInstanceAdmin: true,
        companyIds: [companyId],
      };
      next();
    });
    app.use("/api", issueRoutes(db, {} as never));
    app.use(errorHandler);

    const res = await request(app).get(`/api/companies/${companyId}/issues?includeRoutineExecutions=true`);

    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(1);
    expect(res.body[0]).toMatchObject({
      title: "Projected task with Agency assignee",
      executionAgentNameKey: "agency-backend-engineer",
      agencyAssigneeHealth: {
        name: "agency-backend-engineer",
        department: "engineering",
        skills: ["api", "server"],
        online: false,
        disabled: false,
        status: "sleeping",
        peerId: null,
        peerIdRedacted: true,
        lastSeen: "2026-07-10T02:00:00.000Z",
      },
    });
  });

  it("keeps the issue list API available when Agency roster health is unreadable", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_missing_roster",
        title: "Projected task without readable roster",
        assignee: "agency-backend-engineer",
        status: "todo",
        priority: 50,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    process.env.HERMES_AGENCY_ROSTER_PATH = join(dir, "missing-roster-state.json");

    const app = express();
    app.use(express.json());
    app.use((req, _res, next) => {
      (req as any).actor = {
        type: "board",
        source: "local_implicit",
        userId: "board-user",
        isInstanceAdmin: true,
        companyIds: [companyId],
      };
      next();
    });
    app.use("/api", issueRoutes(db, {} as never));
    app.use(errorHandler);

    const res = await request(app).get(`/api/companies/${companyId}/issues?includeRoutineExecutions=true`);

    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(1);
    expect(res.body[0]).toMatchObject({
      title: "Projected task without readable roster",
      executionAgentNameKey: "agency-backend-engineer",
      agencyAssigneeHealth: null,
    });
  });

  it("is idempotent across repeated syncs", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_repeat",
        title: "Repeatable task",
        status: "todo",
        priority: 10,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const first = await syncHermesKanbanIssues(db, companyId);
    const second = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");
    expect(second.status).toBe("ok");
    expect(second.syncedCount).toBe(0);

    const projectedRows = await db
      .select({ id: issues.id, originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(projectedRows).toHaveLength(1);
    expect(projectedRows[0]?.originId).toBe("t_repeat");
  });

  it("hides stale projected issues, removes stale blocker relations, and keeps surviving projections current", async () => {
    const companyId = await seedCompany();
    const createdAt = 1_782_827_060;
    const { dir, dbPath } = seedKanbanDb({
      tasks: [
        {
          id: "t_parent",
          title: "Projected parent task",
          status: "running",
          priority: 98,
          createdAt,
          startedAt: createdAt + 10,
        },
        {
          id: "t_child",
          title: "Projected child task",
          status: "blocked",
          priority: 45,
          createdAt,
          blockKind: "needs_input",
        },
      ],
      links: [{ parentId: "t_parent", childId: "t_child" }],
      taskEvents: [{ taskId: "t_child", kind: "blocked", payload: { reason: "Waiting for review" } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const first = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");
    expect(first.projectedCount).toBe(2);

    overwriteKanbanDb(dbPath, {
      tasks: [{
        id: "t_child",
        title: "Projected child task (updated)",
        status: "done",
        priority: 72,
        createdAt,
        completedAt: createdAt + 120,
      }],
      links: [],
      taskEvents: [],
    });

    const second = await syncHermesKanbanIssues(db, companyId);
    expect(second.status).toBe("ok");
    expect(second.projectedCount).toBe(1);
    expect(second.syncedCount).toBeGreaterThanOrEqual(2);

    const projectedRows = await db
      .select({
        id: issues.id,
        originId: issues.originId,
        title: issues.title,
        status: issues.status,
        priority: issues.priority,
        hiddenAt: issues.hiddenAt,
        completedAt: issues.completedAt,
      })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(projectedRows).toHaveLength(2);

    const hiddenParent = projectedRows.find((row) => row.originId === "t_parent");
    const survivingChild = projectedRows.find((row) => row.originId === "t_child");
    expect(hiddenParent?.hiddenAt).not.toBeNull();
    expect(survivingChild?.hiddenAt).toBeNull();
    expect(survivingChild?.title).toBe("Projected child task (updated)");
    expect(survivingChild?.status).toBe("done");
    expect(survivingChild?.priority).toBe("high");
    expect(survivingChild?.completedAt).not.toBeNull();

    const blockerRelations = await db
      .select({ issueId: issueRelations.issueId, relatedIssueId: issueRelations.relatedIssueId })
      .from(issueRelations)
      .where(eq(issueRelations.companyId, companyId));
    expect(blockerRelations).toHaveLength(0);

    const issueList = await svc.list(companyId, { includeBlockedBy: true, includeRoutineExecutions: true });
    expect(issueList.map((issue) => issue.title)).toContain("Projected child task (updated)");
    expect(issueList.map((issue) => issue.title)).not.toContain("Projected parent task");
    const visibleChild = issueList.find((issue) => issue.originId === "t_child");
    expect(visibleChild?.blockedBy ?? []).toHaveLength(0);
  });

  it("hides stale projected issues even when the latest Hermes snapshot is empty", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_empty_cleanup",
        title: "Task removed from Hermes",
        status: "running",
        priority: 50,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const first = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");
    expect(first.projectedCount).toBe(1);

    overwriteKanbanDb(dbPath, { tasks: [] });

    const second = await syncHermesKanbanIssues(db, companyId);
    expect(second.status).toBe("ok");
    expect(second.projectedCount).toBe(0);
    expect(second.syncedCount).toBeGreaterThanOrEqual(1);

    const projectedRows = await db
      .select({ originId: issues.originId, hiddenAt: issues.hiddenAt })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(projectedRows).toHaveLength(1);
    expect(projectedRows[0]?.originId).toBe("t_empty_cleanup");
    expect(projectedRows[0]?.hiddenAt).not.toBeNull();

    const issueList = await svc.list(companyId, { includeRoutineExecutions: true });
    expect(issueList.map((issue) => issue.title)).not.toContain("Task removed from Hermes");
  });

  it("does not project Hermes tasks into an unrelated company when scope is pinned", async () => {
    const allowedCompanyId = await seedCompany("Allowed");
    const unrelatedCompanyId = await seedCompany("Unrelated");
    await svc.create(unrelatedCompanyId, {
      title: "Existing unrelated native issue",
      description: "native",
      status: "todo",
      priority: "medium",
      originKind: "manual",
    });

    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_scoped",
        title: "Scoped task",
        status: "running",
        priority: 95,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = allowedCompanyId;

    const allowedSync = await syncHermesKanbanIssues(db, allowedCompanyId);
    const unrelatedSync = await syncHermesKanbanIssues(db, unrelatedCompanyId);
    expect(allowedSync.status).toBe("ok");
    expect(allowedSync.projectedCount).toBe(1);
    expect(unrelatedSync.status).toBe("ok");
    expect(unrelatedSync.projectedCount).toBe(0);
    expect(unrelatedSync.syncedCount).toBe(0);

    const allowedProjectedRows = await db
      .select({ originId: issues.originId, companyId: issues.companyId })
      .from(issues)
      .where(and(eq(issues.companyId, allowedCompanyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    const unrelatedProjectedRows = await db
      .select({ originId: issues.originId, companyId: issues.companyId })
      .from(issues)
      .where(and(eq(issues.companyId, unrelatedCompanyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(allowedProjectedRows).toHaveLength(1);
    expect(allowedProjectedRows[0]?.originId).toBe("t_scoped");
    expect(unrelatedProjectedRows).toHaveLength(0);

    const unrelatedIssueList = await svc.list(unrelatedCompanyId, { includeRoutineExecutions: true });
    expect(unrelatedIssueList.map((issue) => issue.title)).toContain("Existing unrelated native issue");
    expect(unrelatedIssueList.map((issue) => issue.title)).not.toContain("Scoped task");
  });

  it("reports unavailable and leaves native issues alone without explicit projection scope", async () => {
    const firstCompanyId = await seedCompany("First");
    const secondCompanyId = await seedCompany("Second");
    await svc.create(firstCompanyId, {
      title: "Existing native issue",
      description: "native",
      status: "todo",
      priority: "medium",
      originKind: "manual",
    });

    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_unscoped",
        title: "Unscoped task",
        status: "running",
        priority: 95,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    delete process.env.FABRIC_HERMES_KANBAN_COMPANY_ID;
    delete process.env.PAPERCLIP_HERMES_KANBAN_COMPANY_ID;

    const sync = await syncHermesKanbanIssues(db, firstCompanyId);
    expect(sync.status).toBe("unavailable");
    expect(sync.projectedCount).toBe(0);
    expect(sync.syncedCount).toBe(0);
    expect(sync.message).toContain("FABRIC_HERMES_KANBAN_DB");
    expect(sync.message).toContain("FABRIC_HERMES_KANBAN_COMPANY_ID");

    const firstProjectedRows = await db
      .select({ originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, firstCompanyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    const secondProjectedRows = await db
      .select({ originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, secondCompanyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(firstProjectedRows).toHaveLength(0);
    expect(secondProjectedRows).toHaveLength(0);

    const firstIssueList = await svc.list(firstCompanyId, { includeRoutineExecutions: true });
    const secondIssueList = await svc.list(secondCompanyId, { includeRoutineExecutions: true });
    expect(firstIssueList.map((issue) => issue.title)).toContain("Existing native issue");
    expect(firstIssueList.map((issue) => issue.title)).not.toContain("Unscoped task");
    expect(secondIssueList.map((issue) => issue.title)).not.toContain("Unscoped task");
  });

  it("does not project for a single company without explicit projection scope", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_single_unscoped",
        title: "Single unscoped task",
        status: "running",
        priority: 95,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    delete process.env.FABRIC_HERMES_KANBAN_COMPANY_ID;
    delete process.env.PAPERCLIP_HERMES_KANBAN_COMPANY_ID;

    const sync = await syncHermesKanbanIssues(db, companyId);
    expect(sync.status).toBe("unavailable");
    expect(sync.projectedCount).toBe(0);
    expect(sync.syncedCount).toBe(0);

    const projectedRows = await db
      .select({ originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(projectedRows).toHaveLength(0);
  });

  it("reports error when the configured Hermes Kanban DB is missing", async () => {
    const companyId = await seedCompany();
    process.env.FABRIC_HERMES_KANBAN_DB = join(tmpdir(), `missing-${randomUUID()}.db`);
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const sync = await syncHermesKanbanIssues(db, companyId);
    expect(sync.status).toBe("error");
    expect(sync.message).toContain("Hermes Kanban DB not found");
  });

  it("projects tasks when the background sync worker ticks", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_background_worker",
        title: "Background projected task",
        status: "running",
        priority: 75,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const worker = createHermesKanbanProjectionSyncWorker(db);
    worker.start();
    await worker.triggerNow();
    worker.stop();

    const issueList = await svc.list(companyId, { includeRoutineExecutions: true });
    expect(issueList.map((issue) => issue.title)).toContain("Background projected task");
  });

  it("exposes the Hermes Kanban projection status endpoint", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_status_endpoint",
        title: "Status endpoint task",
        status: "running",
        priority: 75,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    await syncHermesKanbanIssues(db, companyId);

    const app = express();
    app.use(express.json());
    app.use((req, _res, next) => {
      (req as any).actor = {
        type: "board",
        source: "local_implicit",
        userId: "board-user",
        isInstanceAdmin: true,
        companyIds: [companyId],
      };
      next();
    });
    app.use("/api/hermes-agency", hermesAgencyRoutes(db));

    const res = await request(app).get("/api/hermes-agency/kanban-projection/status");
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      enabled: true,
      dbPath,
      companyId,
      lastStatus: "ok",
      projectedCount: 1,
    });
    expect(typeof res.body.lastSyncAt).toBe("string");
    expect(res.body.syncedCount).toBeGreaterThanOrEqual(1);
    expect(res.body.lastError).toBeNull();
  });

  it("forbids projection status access for board users outside the configured company", async () => {
    const configuredCompanyId = await seedCompany("Configured");
    const unrelatedCompanyId = await seedCompany("Unrelated");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_status_forbidden",
        title: "Forbidden status endpoint task",
        status: "running",
        priority: 75,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = configuredCompanyId;

    const app = express();
    app.use(express.json());
    app.use((req, _res, next) => {
      (req as any).actor = {
        type: "board",
        source: "session",
        userId: "board-user",
        isInstanceAdmin: false,
        companyIds: [unrelatedCompanyId],
      };
      next();
    });
    app.use("/api/hermes-agency", hermesAgencyRoutes(db));
    app.use(errorHandler);

    const res = await request(app).get("/api/hermes-agency/kanban-projection/status");
    expect(res.status).toBe(403);
    expect(res.body.error).toBe("User does not have access to this company");

    const projectedRows = await db
      .select({ originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, configuredCompanyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(projectedRows).toHaveLength(0);
  });

  it("allows instance admins to read projection status without configured company membership", async () => {
    const configuredCompanyId = await seedCompany("Configured Admin");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_status_admin",
        title: "Admin status endpoint task",
        status: "running",
        priority: 75,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = configuredCompanyId;
    await syncHermesKanbanIssues(db, configuredCompanyId);

    const app = express();
    app.use(express.json());
    app.use((req, _res, next) => {
      (req as any).actor = {
        type: "board",
        source: "session",
        userId: "admin-user",
        isInstanceAdmin: true,
        companyIds: [],
      };
      next();
    });
    app.use("/api/hermes-agency", hermesAgencyRoutes(db));

    const res = await request(app).get("/api/hermes-agency/kanban-projection/status");
    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      enabled: true,
      dbPath,
      companyId: configuredCompanyId,
      lastStatus: "ok",
      projectedCount: 1,
    });
  });

  it("hides duplicate unhidden projections from sync races and keeps the canonical row", async () => {
    const companyId = await seedCompany();
    const createdAt = 1_782_827_060;
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_dup_race",
        title: "Sync race task",
        status: "running",
        priority: 80,
        createdAt,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    // First sync creates the canonical projection
    const first = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");
    expect(first.syncedCount).toBeGreaterThanOrEqual(1);

    const canonicalRows = await db
      .select({ id: issues.id, issueNumber: issues.issueNumber, identifier: issues.identifier })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(canonicalRows).toHaveLength(1);
    const canonicalId = canonicalRows[0]!.id;
    const canonicalNumber = canonicalRows[0]!.issueNumber;

    // Simulate a sync race: insert a second unhidden row with the same originId
    const dupIssueNumber = canonicalNumber + 1;
    const [company] = await db
      .select({ issuePrefix: companies.issuePrefix })
      .from(companies)
      .where(eq(companies.id, companyId));
    const dupIdentifier = `${company!.issuePrefix}-${dupIssueNumber}`;
    await db.insert(issues).values({
      companyId,
      title: "Sync race task (duplicate)",
      description: "duplicate from race",
      status: "in_progress",
      workMode: "standard",
      priority: "high",
      issueNumber: dupIssueNumber,
      identifier: dupIdentifier,
      originKind: HERMES_KANBAN_TASK_ORIGIN_KIND,
      originId: "t_dup_race",
      originFingerprint: "hermes-kanban:t_dup_race",
      requestDepth: 0,
      createdAt: new Date(createdAt * 1000),
      updatedAt: new Date(createdAt * 1000),
    });
    // Update company counter to match
    await db.update(companies).set({ issueCounter: dupIssueNumber }).where(eq(companies.id, companyId));

    // Verify both rows are unhidden before the cleanup sync
    const preSyncRows = await db
      .select({ id: issues.id, hiddenAt: issues.hiddenAt, originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(preSyncRows).toHaveLength(2);
    expect(preSyncRows.every((r) => r.hiddenAt === null)).toBe(true);

    // Second sync should detect and hide the duplicate
    const second = await syncHermesKanbanIssues(db, companyId);
    expect(second.status).toBe("ok");
    expect(second.syncedCount).toBeGreaterThanOrEqual(1); // hide duplicate

    const postSyncRows = await db
      .select({ id: issues.id, hiddenAt: issues.hiddenAt, originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND)));
    expect(postSyncRows).toHaveLength(2);

    const canonical = postSyncRows.find((r) => r.id === canonicalId);
    const duplicate = postSyncRows.find((r) => r.id !== canonicalId);
    expect(canonical?.hiddenAt).toBeNull();
    expect(duplicate?.hiddenAt).not.toBeNull();

    // Only the canonical row should be visible in the issue list
    const issueList = await svc.list(companyId, { includeRoutineExecutions: true });
    const projectedIssues = issueList.filter((i) => i.originId === "t_dup_race");
    expect(projectedIssues).toHaveLength(1);
    expect(projectedIssues[0]!.id).toBe(canonicalId);
  });

  it("is idempotent when duplicate projections exist across repeated syncs", async () => {
    const companyId = await seedCompany();
    const createdAt = 1_782_827_060;
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_dup_idempotent",
        title: "Idempotent dup task",
        status: "todo",
        priority: 30,
        createdAt,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    // First sync
    const first = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");

    // Inject a duplicate
    const [company] = await db
      .select({ issuePrefix: companies.issuePrefix, issueCounter: companies.issueCounter })
      .from(companies)
      .where(eq(companies.id, companyId));
    const dupNumber = (company!.issueCounter as number) + 1;
    await db.insert(issues).values({
      companyId,
      title: "Idempotent dup task (dup)",
      description: "duplicate",
      status: "todo",
      workMode: "standard",
      priority: "low",
      issueNumber: dupNumber,
      identifier: `${company!.issuePrefix}-${dupNumber}`,
      originKind: HERMES_KANBAN_TASK_ORIGIN_KIND,
      originId: "t_dup_idempotent",
      originFingerprint: "hermes-kanban:t_dup_idempotent",
      requestDepth: 0,
      createdAt: new Date(createdAt * 1000),
      updatedAt: new Date(createdAt * 1000),
    });
    await db.update(companies).set({ issueCounter: dupNumber }).where(eq(companies.id, companyId));

    // Second sync cleans up duplicate
    const second = await syncHermesKanbanIssues(db, companyId);
    expect(second.status).toBe("ok");
    expect(second.syncedCount).toBeGreaterThanOrEqual(1);

    // Third sync should be a no-op (idempotent after cleanup)
    const third = await syncHermesKanbanIssues(db, companyId);
    expect(third.status).toBe("ok");
    expect(third.syncedCount).toBe(0);

    // Still exactly one unhidden projection
    const unhiddenRows = await db
      .select({ id: issues.id })
      .from(issues)
      .where(and(
        eq(issues.companyId, companyId),
        eq(issues.originKind, HERMES_KANBAN_TASK_ORIGIN_KIND),
        isNull(issues.hiddenAt),
      ));
    expect(unhiddenRows).toHaveLength(1);
  });

  it("preserves the canonical blocked projection when a duplicate unhidden row exists", async () => {
    const companyId = await seedCompany();
    const createdAt = 1_782_827_060;
    const { dir, dbPath } = seedKanbanDb({
      tasks: [
        {
          id: "t_blocker",
          title: "Blocker task",
          status: "running",
          priority: 90,
          createdAt,
        },
        {
          id: "t_blocked_canonical",
          title: "Blocked task (canonical)",
          status: "blocked",
          priority: 50,
          createdAt,
          blockKind: "dependency",
        },
      ],
      links: [{ parentId: "t_blocker", childId: "t_blocked_canonical" }],
      taskEvents: [{ taskId: "t_blocked_canonical", kind: "blocked", payload: { reason: "Waiting on blocker" } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    // First sync creates both projections and the blocker relation
    const first = await syncHermesKanbanIssues(db, companyId);
    expect(first.status).toBe("ok");

    const canonicalBlocked = await db
      .select({ id: issues.id, issueNumber: issues.issueNumber, status: issues.status })
      .from(issues)
      .where(and(
        eq(issues.companyId, companyId),
        eq(issues.originId, "t_blocked_canonical"),
        isNull(issues.hiddenAt),
      ));
    expect(canonicalBlocked).toHaveLength(1);
    expect(canonicalBlocked[0]!.status).toBe("blocked");
    const canonicalBlockedId = canonicalBlocked[0]!.id;

    // Verify blocker relation exists
    const relations = await db
      .select({ issueId: issueRelations.issueId, relatedIssueId: issueRelations.relatedIssueId })
      .from(issueRelations)
      .where(and(eq(issueRelations.companyId, companyId), eq(issueRelations.type, "blocks")));
    expect(relations).toHaveLength(1);
    expect(relations[0]!.relatedIssueId).toBe(canonicalBlockedId);

    // Inject a duplicate unhidden row for the blocked task
    const [company] = await db
      .select({ issuePrefix: companies.issuePrefix, issueCounter: companies.issueCounter })
      .from(companies)
      .where(eq(companies.id, companyId));
    const dupNumber = (company!.issueCounter as number) + 1;
    const dupIdentifier = `${company!.issuePrefix}-${dupNumber}`;
    await db.insert(issues).values({
      companyId,
      title: "Blocked task (duplicate)",
      description: "duplicate",
      status: "blocked",
      workMode: "standard",
      priority: "medium",
      issueNumber: dupNumber,
      identifier: dupIdentifier,
      originKind: HERMES_KANBAN_TASK_ORIGIN_KIND,
      originId: "t_blocked_canonical",
      originFingerprint: "hermes-kanban:t_blocked_canonical",
      requestDepth: 0,
      createdAt: new Date(createdAt * 1000),
      updatedAt: new Date(createdAt * 1000),
    });
    await db.update(companies).set({ issueCounter: dupNumber }).where(eq(companies.id, companyId));

    // Second sync should hide the duplicate and preserve the canonical blocked projection
    const second = await syncHermesKanbanIssues(db, companyId);
    expect(second.status).toBe("ok");

    const postSyncRows = await db
      .select({ id: issues.id, hiddenAt: issues.hiddenAt, status: issues.status, originId: issues.originId })
      .from(issues)
      .where(and(eq(issues.companyId, companyId), eq(issues.originId, "t_blocked_canonical")));
    expect(postSyncRows).toHaveLength(2);

    const surviving = postSyncRows.find((r) => r.hiddenAt === null);
    const hidden = postSyncRows.find((r) => r.hiddenAt !== null);
    expect(surviving?.id).toBe(canonicalBlockedId);
    expect(surviving?.status).toBe("blocked");
    expect(hidden?.id).not.toBe(canonicalBlockedId);

    // Blocker relation should still point to the canonical
    const postRelations = await db
      .select({ issueId: issueRelations.issueId, relatedIssueId: issueRelations.relatedIssueId })
      .from(issueRelations)
      .where(and(eq(issueRelations.companyId, companyId), eq(issueRelations.type, "blocks")));
    expect(postRelations).toHaveLength(1);
    expect(postRelations[0]!.relatedIssueId).toBe(canonicalBlockedId);
  });
});
