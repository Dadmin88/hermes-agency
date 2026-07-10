import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { randomUUID } from "node:crypto";
import express from "express";
import request from "supertest";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { and, eq, isNull, sql } from "drizzle-orm";
import {
  agents,
  activityLog,
  approvals,
  authUsers,
  companies,
  companyMemberships,
  createDb,
  issueApprovals,
  issueLabels,
  issueRelations,
  issues,
  labels,
  projects,
  projectWorkspaces,
} from "@paperclipai/db";
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

import { issueRoutes } from "../routes/issues.ts";
import { errorHandler } from "../middleware/error-handler.ts";
import { issueService } from "../services/issues.ts";
import {
  hermesKanbanReverseSyncService,
  resolveHermesKanbanBoard,
} from "../services/hermes-kanban-reverse-sync.ts";

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

describe("resolveHermesKanbanBoard", () => {
  it("prefers the Fabric-scoped board and falls back to the Hermes board", () => {
    expect(resolveHermesKanbanBoard({
      FABRIC_HERMES_KANBAN_BOARD: "fabric-board",
      HERMES_KANBAN_BOARD: "ambient-board",
    })).toBe("fabric-board");
    expect(resolveHermesKanbanBoard({ HERMES_KANBAN_BOARD: "ambient-board" }))
      .toBe("ambient-board");
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
    metadata?: Record<string, unknown> | null;
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
      run.metadata ? JSON.stringify(run.metadata) : null,
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
    await db.delete(issueApprovals);
    await db.delete(approvals);
    await db.delete(issueLabels);
    await db.delete(labels);
    await db.delete(activityLog);
    await db.delete(issueRelations);
    await db.delete(issues);
    await db.delete(projectWorkspaces);
    await db.delete(projects);
    await db.delete(agents);
    await db.delete(companyMemberships);
    await db.delete(companies);
    await db.delete(authUsers);
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

  async function seedAgent(companyId: string, name: string) {
    const [agent] = await db.insert(agents).values({
      companyId,
      name,
      role: "engineer",
      metadata: { name_key: name },
    }).returning({ id: agents.id });
    return agent!.id;
  }

  async function seedUser(companyId: string, name: string) {
    const userId = randomUUID();
    const now = new Date();
    await db.insert(authUsers).values({
      id: userId,
      name,
      email: `${userId}@example.com`,
      emailVerified: true,
      createdAt: now,
      updatedAt: now,
    });
    await db.insert(companyMemberships).values({
      companyId,
      principalType: "user",
      principalId: userId,
      status: "active",
      membershipRole: "operator",
    });
    return userId;
  }

  async function seedProject(companyId: string, name: string, workspacePath?: string) {
    const [project] = await db.insert(projects).values({
      companyId,
      name,
      status: "active",
    }).returning({ id: projects.id });
    let workspaceId: string | null = null;
    if (workspacePath) {
      const [workspace] = await db.insert(projectWorkspaces).values({
        companyId,
        projectId: project!.id,
        name: `${name} workspace`,
        cwd: workspacePath,
        isPrimary: true,
      }).returning({ id: projectWorkspaces.id });
      workspaceId = workspace!.id;
    }
    return { projectId: project!.id, workspaceId };
  }

  async function projectedIssueRow(originId: string) {
    const [issue] = await db.select().from(issues).where(eq(issues.originId, originId)).limit(1);
    return issue!;
  }

  async function issueLabelNames(issueId: string) {
    const rows = await db.select({ name: labels.name }).from(issueLabels)
      .innerJoin(labels, eq(issueLabels.labelId, labels.id))
      .where(eq(issueLabels.issueId, issueId));
    return rows.map((row) => row.name).sort();
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

  it("enriches projected issues from structured Hermes metadata", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedAgent(companyId, "agency-code-reviewer");
    const approverId = await seedAgent(companyId, "agency-security-reviewer");
    const { projectId, workspaceId } = await seedProject(companyId, "Hermes Agency", "/home/dadmin/repos/Hermes_Agency");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_structured", title: "Structured metadata task", status: "running", priority: 80, createdAt: 1_782_827_060 }],
      taskRuns: [{
        taskId: "t_structured",
        metadata: {
          fabric: {
            project: { key: "Hermes Agency", workspace_path: "/home/dadmin/repos/Hermes_Agency" },
            labels: [{ name: "review", color: "#a855f7" }, { name: "server", color: "#22c55e" }],
            reviewers: [{ agent_name_key: "agency-code-reviewer", required: true, reason: "code_change" }],
            approvers: [{ agent_name_key: "agency-security-reviewer", required: true, reason: "security_sensitive" }],
            execution_policy: { mode: "autonomous_validated" },
            source_trust: { preset: "standard", disposition: "promoted" },
          },
          hermes_agency: { execution_agent_name_key: "agency-code-reviewer", requested_skills: ["code-review"] },
        },
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    const sync = await syncHermesKanbanIssues(db, companyId);
    expect(sync.status).toBe("ok");
    const issue = await projectedIssueRow("t_structured");
    expect(issue.assigneeAgentId).toBe(reviewerId);
    expect(issue.projectId).toBe(projectId);
    expect(issue.projectWorkspaceId).toBe(workspaceId);
    expect(issue.executionPolicy).toMatchObject({ mode: "autonomous_validated" });
    expect(issue.sourceTrust).toMatchObject({ preset: "standard", disposition: "promoted" });
    expect(issue.executionState).toMatchObject({
      hermesKanbanProjection: {
        provenance: expect.arrayContaining(["task_run_metadata", "structured_metadata"]),
        managedFields: {
          assigneeAgentId: { owner: "hermes_kanban_projection", value: reviewerId },
          projectId: { owner: "hermes_kanban_projection", value: projectId },
          projectWorkspaceId: { owner: "hermes_kanban_projection", value: workspaceId },
          executionPolicy: { owner: "hermes_kanban_projection", value: { mode: "autonomous_validated" } },
        },
      },
    });
    expect(await issueLabelNames(issue.id)).toEqual(expect.arrayContaining(["kanban", "review", "server"]));
    const linkedApprovals = await db.select({
      type: approvals.type,
      status: approvals.status,
      requestedByAgentId: approvals.requestedByAgentId,
      payload: approvals.payload,
    }).from(issueApprovals)
      .innerJoin(approvals, eq(issueApprovals.approvalId, approvals.id))
      .where(eq(issueApprovals.issueId, issue.id));
    expect(linkedApprovals.map((row) => row.type).sort()).toEqual(["approval_required", "review_required"]);
    expect(linkedApprovals.every((row) => row.status === "pending")).toBe(true);
    expect(linkedApprovals.every((row) => row.requestedByAgentId === reviewerId)).toBe(true);
    expect(linkedApprovals).toEqual(expect.arrayContaining([
      expect.objectContaining({
        type: "review_required",
        payload: expect.objectContaining({
          reviewerAgentNameKey: "agency-code-reviewer",
          reviewerAgentId: reviewerId,
          reason: "code_change",
          source: "hermes_kanban_projection",
        }),
      }),
      expect.objectContaining({
        type: "approval_required",
        payload: expect.objectContaining({
          approverAgentNameKey: "agency-security-reviewer",
          approverAgentId: approverId,
          reason: "security_sensitive",
          source: "hermes_kanban_projection",
        }),
      }),
    ]));
  });

  it("prefers latest structured event metadata over run metadata and the legacy body fallback", async () => {
    const companyId = await seedCompany();
    const runAgentId = await seedAgent(companyId, "agency-backend-engineer");
    const eventAgentId = await seedAgent(companyId, "agency-code-reviewer");
    await seedAgent(companyId, "agency-frontend-engineer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_metadata_precedence",
        title: "Metadata precedence",
        body: 'Hermes Agency metadata:\n```json\n{"target_profile":"agency-frontend-engineer"}\n```',
        status: "todo",
        priority: 50,
        createdAt: 1_782_827_060,
      }],
      taskRuns: [{
        taskId: "t_metadata_precedence",
        metadata: {
          fabric: { execution_policy: { mode: "run", blocked_actions: ["deploy"] } },
          hermes_agency: { target_profile: "agency-backend-engineer" },
        },
      }],
      taskEvents: [{
        taskId: "t_metadata_precedence",
        kind: "metadata",
        payload: {
          fabric: { execution_policy: { mode: "event" } },
          hermes_agency: { target_profile: "agency-code-reviewer" },
        },
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_metadata_precedence");
    expect(issue.assigneeAgentId).toBe(eventAgentId);
    expect(issue.assigneeAgentId).not.toBe(runAgentId);
    expect(issue.executionAgentNameKey).toBe("agency-code-reviewer");
    expect(issue.executionPolicy).toMatchObject({ mode: "event", blocked_actions: ["deploy"] });
    expect(issue.executionState).toMatchObject({
      hermesKanbanProjection: {
        provenance: expect.arrayContaining(["task_run_metadata", "task_event", "structured_metadata"]),
      },
    });
    expect(JSON.stringify(issue.executionState)).not.toContain("legacy_body_fallback");
  });

  it("infers assignee and labels safely when structured metadata is missing", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedAgent(companyId, "agency-code-reviewer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_infer", title: "Review inferred task", assignee: "agency-code-reviewer", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_infer");
    expect(issue.assigneeAgentId).toBe(reviewerId);
    expect(issue.executionAgentNameKey).toBe("agency-code-reviewer");
    expect(issue.executionState).toMatchObject({
      hermesKanbanProjection: {
        provenance: expect.arrayContaining(["inference"]),
        managedFields: { assigneeAgentId: { owner: "hermes_kanban_projection", value: reviewerId } },
      },
    });
    expect(await issueLabelNames(issue.id)).toEqual(expect.arrayContaining(["kanban", "review"]));
  });

  it("leaves unknown agent and project unresolved with projection warnings", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_unknown", title: "Unknown metadata task", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
      taskEvents: [{ taskId: "t_unknown", kind: "created", payload: {
        fabric: { project: { key: "Missing Project" } },
        hermes_agency: { target_profile: "agency-missing-reviewer" },
      } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_unknown");
    expect(issue.assigneeAgentId).toBeNull();
    expect(issue.projectId).toBeNull();
    expect(issue.executionState).toMatchObject({
      hermesKanbanProjection: { warnings: expect.arrayContaining([
        expect.stringContaining("agency-missing-reviewer"),
        expect.stringContaining("Missing Project"),
      ]) },
    });
  });

  it("preserves manual assignee, project, labels, and decided approvals across re-sync", async () => {
    const companyId = await seedCompany();
    await seedAgent(companyId, "agency-code-reviewer");
    const manualAgentId = await seedAgent(companyId, "agency-fullstack-engineer");
    await seedProject(companyId, "Hermes Agency");
    const manualProject = await seedProject(companyId, "Manual Project");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_manual", title: "Manual override task", assignee: "agency-code-reviewer", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_manual");
    const [manualLabel] = await db.insert(labels).values({ companyId, name: "manual", color: "#111827" }).returning({ id: labels.id });
    await db.insert(issueLabels).values({ companyId, issueId: issue.id, labelId: manualLabel!.id });
    const [decidedApproval] = await db.insert(approvals).values({
      companyId,
      type: "approval_required",
      status: "approved",
      payload: { projectionFingerprint: "manual-decision" },
    }).returning({ id: approvals.id });
    await db.insert(issueApprovals).values({ companyId, issueId: issue.id, approvalId: decidedApproval!.id });
    await db.update(issues).set({ assigneeAgentId: manualAgentId, projectId: manualProject.projectId }).where(eq(issues.id, issue.id));

    overwriteKanbanDb(dbPath, {
      tasks: [{ id: "t_manual", title: "Manual override task", assignee: "agency-code-reviewer", status: "running", priority: 70, createdAt: 1_782_827_060 }],
      taskRuns: [{ taskId: "t_manual", metadata: { fabric: { project: { key: "Hermes Agency" }, labels: [{ name: "review" }] } } }],
    });
    await syncHermesKanbanIssues(db, companyId);
    const updated = await projectedIssueRow("t_manual");
    expect(updated.assigneeAgentId).toBe(manualAgentId);
    expect(updated.projectId).toBe(manualProject.projectId);
    expect(await issueLabelNames(issue.id)).toEqual(expect.arrayContaining(["manual", "kanban", "review"]));
    const [approval] = await db.select({ status: approvals.status }).from(approvals).where(eq(approvals.id, decidedApproval!.id));
    expect(approval?.status).toBe("approved");
    expect(updated.executionState).toMatchObject({ hermesKanbanProjection: { warnings: expect.arrayContaining([expect.stringContaining("Preserved manual assignee")]) } });
  });

  it("reconciles projection-owned labels after an accepted allowlisted removal intent", async () => {
    const companyId = await seedCompany();
    const initialTask = { id: "t_label_removal", title: "Label removal", status: "todo", priority: 50, createdAt: 1_782_827_060 };
    const initialRun = {
      taskId: "t_label_removal",
      metadata: { fabric: { labels: [{ name: "risk:security", color: "#ef4444" }] } },
    };
    const { dir, dbPath } = seedKanbanDb({ tasks: [initialTask], taskRuns: [initialRun] });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_label_removal");
    const [manualLabel] = await db.insert(labels).values({ companyId, name: "fabric-local", color: "#111827" })
      .returning({ id: labels.id });
    await db.insert(issueLabels).values({ companyId, issueId: issue.id, labelId: manualLabel!.id });
    const [removedLabel] = await db.select({ id: labels.id }).from(labels)
      .where(and(eq(labels.companyId, companyId), eq(labels.name, "risk:security")));
    await db.delete(issueLabels).where(and(eq(issueLabels.issueId, issue.id), eq(issueLabels.labelId, removedLabel!.id)));

    overwriteKanbanDb(dbPath, {
      tasks: [initialTask],
      taskRuns: [initialRun],
      taskEvents: [{
        taskId: "t_label_removal",
        kind: "fabric_metadata_sync",
        payload: { source: "fabric_properties", fabric: { label_intents: { add: [], removal_intent: ["risk:security"] } } },
      }],
    });
    await syncHermesKanbanIssues(db, companyId);
    const updated = await projectedIssueRow("t_label_removal");
    expect(await issueLabelNames(issue.id)).toEqual(["fabric-local", "kanban"]);
    expect(updated.executionState).toMatchObject({
      hermesKanbanProjection: {
        managedFields: { labels: { owner: "hermes_kanban_projection", value: ["kanban"] } },
      },
    });
    expect((await syncHermesKanbanIssues(db, companyId)).syncedCount).toBe(0);
    expect(await issueLabelNames(issue.id)).toEqual(["fabric-local", "kanban"]);
  });

  it("unlinks stale pending projected governance while preserving decided and manual approvals", async () => {
    const companyId = await seedCompany();
    await seedAgent(companyId, "agency-old-reviewer");
    await seedAgent(companyId, "agency-removed-reviewer");
    await seedAgent(companyId, "agency-new-reviewer");
    await seedAgent(companyId, "agency-old-approver");
    await seedAgent(companyId, "agency-removed-approver");
    await seedAgent(companyId, "agency-new-approver");
    const task = { id: "t_governance_reconcile", title: "Governance reconcile", status: "todo", priority: 50, createdAt: 1_782_827_060 };
    const { dir, dbPath } = seedKanbanDb({
      tasks: [task],
      taskRuns: [{ taskId: task.id, metadata: { fabric: {
        reviewers: [{ agent_name_key: "agency-old-reviewer" }, { agent_name_key: "agency-removed-reviewer" }],
        approvers: [{ agent_name_key: "agency-old-approver" }, { agent_name_key: "agency-removed-approver" }],
        approval_policy: { requires_deploy_approval: true },
      } } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow(task.id);
    const initialRows = await db.select({ id: approvals.id, payload: approvals.payload })
      .from(issueApprovals)
      .innerJoin(approvals, eq(issueApprovals.approvalId, approvals.id))
      .where(eq(issueApprovals.issueId, issue.id));
    expect(initialRows).toHaveLength(5);
    const decided = initialRows.find((row) => row.payload.reviewerAgentNameKey === "agency-old-reviewer")!;
    await db.update(approvals).set({ status: "approved", decidedAt: new Date() }).where(eq(approvals.id, decided.id));
    const [manualApproval] = await db.insert(approvals).values({
      companyId,
      type: "approval_required",
      status: "pending",
      payload: { source: "fabric_manual", reason: "operator gate" },
    }).returning({ id: approvals.id });
    await db.insert(issueApprovals).values({ companyId, issueId: issue.id, approvalId: manualApproval!.id });

    overwriteKanbanDb(dbPath, {
      tasks: [task],
      taskRuns: [{ taskId: task.id, metadata: { fabric: {
        reviewers: [{ agent_name_key: "agency-new-reviewer" }],
        approvers: [{ agent_name_key: "agency-new-approver" }],
        approval_policy: {},
      } } }],
    });
    await syncHermesKanbanIssues(db, companyId);

    const linkedRows = await db.select({ id: approvals.id, status: approvals.status, payload: approvals.payload })
      .from(issueApprovals)
      .innerJoin(approvals, eq(issueApprovals.approvalId, approvals.id))
      .where(eq(issueApprovals.issueId, issue.id));
    expect(linkedRows.map((row) => row.id)).toEqual(expect.arrayContaining([decided.id, manualApproval!.id]));
    expect(linkedRows.find((row) => row.id === decided.id)?.status).toBe("approved");
    const pendingProjected = linkedRows.filter((row) => row.status === "pending" && row.payload.source === "hermes_kanban_projection");
    expect(pendingProjected).toHaveLength(2);
    expect(pendingProjected.map((row) => row.payload.reviewerAgentNameKey).filter(Boolean)).toEqual(["agency-new-reviewer"]);
    expect(pendingProjected.map((row) => row.payload.approverAgentNameKey).filter(Boolean)).toEqual(["agency-new-approver"]);
    expect(linkedRows.some((row) => row.payload.requiresHuman === true)).toBe(false);
    expect(linkedRows).toHaveLength(4);
  });

  it("updates projection-owned fields on resync and creates pending governance requirements", async () => {
    const companyId = await seedCompany();
    const firstAgentId = await seedAgent(companyId, "agency-backend-engineer");
    const secondAgentId = await seedAgent(companyId, "agency-code-reviewer");
    await seedAgent(companyId, "agency-security-reviewer");
    const firstProject = await seedProject(companyId, "First Project");
    const secondProject = await seedProject(companyId, "Second Project");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_owned_resync", title: "Owned resync", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
      taskRuns: [{ taskId: "t_owned_resync", metadata: {
        fabric: { project: { id: firstProject.projectId }, execution_policy: { mode: "first" } },
        hermes_agency: { target_profile: "agency-backend-engineer" },
      } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    await syncHermesKanbanIssues(db, companyId);
    const first = await projectedIssueRow("t_owned_resync");
    expect(first.assigneeAgentId).toBe(firstAgentId);
    expect(first.projectId).toBe(firstProject.projectId);

    overwriteKanbanDb(dbPath, {
      tasks: [{ id: "t_owned_resync", title: "Owned resync", status: "running", priority: 50, createdAt: 1_782_827_060 }],
      taskRuns: [{ taskId: "t_owned_resync", metadata: {
        fabric: {
          project: { id: secondProject.projectId },
          execution_policy: { mode: "second" },
          approval_policy: { requires_security_review: true, requires_deploy_approval: true },
        },
        hermes_agency: { target_profile: "agency-code-reviewer" },
      } }],
    });
    await syncHermesKanbanIssues(db, companyId);
    const second = await projectedIssueRow("t_owned_resync");
    expect(second.assigneeAgentId).toBe(secondAgentId);
    expect(second.projectId).toBe(secondProject.projectId);
    expect(second.executionPolicy).toEqual({ mode: "second" });
    expect(second.executionState).toMatchObject({
      hermesKanbanProjection: {
        managedFields: {
          assigneeAgentId: { owner: "hermes_kanban_projection", value: secondAgentId },
          projectId: { owner: "hermes_kanban_projection", value: secondProject.projectId },
        },
      },
    });
    const governanceRows = await db.select({ type: approvals.type, status: approvals.status, payload: approvals.payload })
      .from(issueApprovals)
      .innerJoin(approvals, eq(issueApprovals.approvalId, approvals.id))
      .where(eq(issueApprovals.issueId, second.id));
    expect(governanceRows).toHaveLength(2);
    expect(governanceRows.every((row) => row.status === "pending")).toBe(true);
    expect(governanceRows.map((row) => row.type).sort()).toEqual(["approval_required", "review_required"]);
    expect(governanceRows.some((row) => row.payload.requiresHuman === true)).toBe(true);
  });

  it("resolves DF-681-style legacy Hermes Agency metadata body fallback", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedAgent(companyId, "agency-code-reviewer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_d3438cc4",
        title: "DF-681 legacy metadata task",
        body: 'Hermes Agency metadata:\n```json\n{"target_profile":"agency-code-reviewer","requested_skills":["code-review"]}\n```',
        status: "todo",
        priority: 50,
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_d3438cc4");
    expect(issue.assigneeAgentId).toBe(reviewerId);
    expect(issue.executionState).toMatchObject({ hermesKanbanProjection: { provenance: expect.arrayContaining(["legacy_body_fallback"]) } });
    expect(await issueLabelNames(issue.id)).toEqual(expect.arrayContaining(["kanban", "review"]));
  });

  it("does not resolve cross-company agent or project names", async () => {
    const companyId = await seedCompany("Primary");
    const otherCompanyId = await seedCompany("Other");
    await seedAgent(otherCompanyId, "agency-code-reviewer");
    await seedProject(otherCompanyId, "Hermes Agency");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_cross_company", title: "Cross company task", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
      taskRuns: [{ taskId: "t_cross_company", metadata: {
        fabric: { project: { key: "Hermes Agency" } },
        hermes_agency: { target_profile: "agency-code-reviewer" },
      } }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;

    await syncHermesKanbanIssues(db, companyId);
    const issue = await projectedIssueRow("t_cross_company");
    expect(issue.assigneeAgentId).toBeNull();
    expect(issue.projectId).toBeNull();
    expect(issue.executionState).toMatchObject({ hermesKanbanProjection: { warnings: expect.arrayContaining([
      expect.stringContaining("agency-code-reviewer"),
      expect.stringContaining("Hermes Agency"),
    ]) } });
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

  it("reverse-syncs a committed Fabric assignee edit through the audited command boundary", async () => {
    const companyId = await seedCompany();
    const firstAgentId = await seedAgent(companyId, "agency-frontend-engineer");
    const secondAgentId = await seedAgent(companyId, "agency-backend-engineer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_reverse_assignee",
        title: "Reverse assignee",
        status: "todo",
        priority: 50,
        assignee: "agency-frontend-engineer",
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await projectedIssueRow("t_reverse_assignee");
    expect(previous.assigneeAgentId).toBe(firstAgentId);
    const [next] = await db.update(issues)
      .set({ assigneeAgentId: secondAgentId })
      .where(eq(issues.id, previous.id))
      .returning();
    const commandRunner = vi.fn(async () => ({ ok: true }));
    const result = await hermesKanbanReverseSyncService(db, { commandRunner })
      .syncCommittedIssueUpdate({
        previous,
        next: next!,
        actor: { actorType: "user", actorId: "operator" },
      });
    expect(result.accepted).toBe(true);
    expect(commandRunner).toHaveBeenCalledWith(expect.objectContaining({
      taskId: "t_reverse_assignee",
      patch: { assignee: "agency-backend-engineer" },
      expectedOriginFingerprint: "hermes-kanban:t_reverse_assignee",
    }));
    const refreshed = await projectedIssueRow("t_reverse_assignee");
    expect(JSON.stringify(refreshed.executionState)).toContain("fabric_manual_override");
  });

  it("does not silently reverse-sync reassignment of a running Hermes task", async () => {
    const companyId = await seedCompany();
    const firstAgentId = await seedAgent(companyId, "agency-frontend-engineer");
    const secondAgentId = await seedAgent(companyId, "agency-backend-engineer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{
        id: "t_reverse_running",
        title: "Running reverse guard",
        status: "running",
        priority: 50,
        assignee: "agency-frontend-engineer",
        createdAt: 1_782_827_060,
      }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await projectedIssueRow("t_reverse_running");
    expect(previous.assigneeAgentId).toBe(firstAgentId);
    const [next] = await db.update(issues)
      .set({ assigneeAgentId: secondAgentId })
      .where(eq(issues.id, previous.id))
      .returning();
    const commandRunner = vi.fn(async () => ({ ok: true }));
    const result = await hermesKanbanReverseSyncService(db, { commandRunner })
      .syncCommittedIssueUpdate({
        previous,
        next: next!,
        actor: { actorType: "user", actorId: "operator" },
      });
    expect(result.accepted).toBe(false);
    expect(result.warning).toContain("interrupt/requeue");
    expect(commandRunner).not.toHaveBeenCalled();
  });

  it("keeps Fabric-local labels local and emits idempotent allowlisted label intents", async () => {
    const companyId = await seedCompany();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_labels", title: "Reverse labels", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await svc.getById((await projectedIssueRow("t_reverse_labels")).id);
    const [localLabel, syncedLabel] = await db.insert(labels).values([
      { companyId, name: "fabric-local", color: "#111827" },
      { companyId, name: "risk:security", color: "#ef4444" },
    ]).returning();
    const local = await svc.update(previous!.id, {
      labelIds: [...previous!.labelIds, localLabel!.id],
    });
    const commandRunner = vi.fn(async () => ({ ok: true }));
    const reverseSync = hermesKanbanReverseSyncService(db, { commandRunner });
    const localResult = await reverseSync.syncCommittedIssueUpdate({
      previous: previous!,
      next: local!,
      actor: { actorType: "user", actorId: "operator" },
    });
    expect(localResult.attempted).toBe(false);
    expect(commandRunner).not.toHaveBeenCalled();

    process.env.FABRIC_HERMES_KANBAN_BOARD = "agency-quality";
    const synced = await svc.update(previous!.id, {
      labelIds: [...local!.labelIds, syncedLabel!.id],
    });
    const syncedResult = await reverseSync.syncCommittedIssueUpdate({
      previous: local!,
      next: synced!,
      actor: { actorType: "user", actorId: "operator" },
    });
    expect(syncedResult.accepted).toBe(true);
    expect(commandRunner).toHaveBeenCalledWith(expect.objectContaining({
      board: "agency-quality",
      dbPath,
      patch: { labels: { add: ["risk:security"], removal_intent: [] } },
    }));
    const removed = await svc.update(synced!.id, {
      labelIds: synced!.labelIds.filter((id) => id !== syncedLabel!.id),
    });
    const removalResult = await reverseSync.syncCommittedIssueUpdate({
      previous: synced!,
      next: removed!,
      actor: { actorType: "user", actorId: "operator" },
    });
    expect(removalResult.accepted).toBe(true);
    expect(commandRunner).toHaveBeenLastCalledWith(expect.objectContaining({
      patch: { labels: { add: [], removal_intent: ["risk:security"] } },
    }));
    const unchanged = await svc.getById(removed!.id);
    const idempotentResult = await reverseSync.syncCommittedIssueUpdate({
      previous: unchanged!,
      next: unchanged!,
      actor: { actorType: "user", actorId: "operator" },
    });
    expect(idempotentResult.attempted).toBe(false);
    expect(commandRunner).toHaveBeenCalledTimes(2);
    delete process.env.FABRIC_HERMES_KANBAN_BOARD;
  });

  it("serializes project, reviewer, approver, and tightening policy metadata", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedAgent(companyId, "agency-code-reviewer");
    const approverId = await seedAgent(companyId, "agency-security-reviewer");
    const project = await seedProject(companyId, "Metadata Project");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_governance", title: "Reverse governance", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await svc.getById((await projectedIssueRow("t_reverse_governance")).id);
    const executionPolicy = {
      mode: "normal" as const,
      commentRequired: true,
      stages: [
        { id: randomUUID(), type: "review" as const, approvalsNeeded: 1 as const, participants: [{ type: "agent" as const, agentId: reviewerId }] },
        { id: randomUUID(), type: "approval" as const, approvalsNeeded: 1 as const, participants: [{ type: "agent" as const, agentId: approverId }] },
      ],
      authorizationPolicy: { production: "approval_required", deploy: "blocked" },
    };
    const next = await svc.update(previous!.id, { projectId: project.projectId, executionPolicy });
    const commandRunner = vi.fn(async () => ({ ok: true }));
    const result = await hermesKanbanReverseSyncService(db, { commandRunner })
      .syncCommittedIssueUpdate({
        previous: previous!,
        next: next!,
        actor: { actorType: "user", actorId: "operator" },
      });
    expect(result.accepted).toBe(true);
    expect(result.fields).toEqual(expect.arrayContaining(["projectId", "reviewers", "approvers", "executionPolicy"]));
    expect(commandRunner).toHaveBeenCalledWith(expect.objectContaining({
      patch: expect.objectContaining({
        project: { id: project.projectId, name: "Metadata Project" },
        reviewers: [{ type: "agent", agent_id: reviewerId, agent_name_key: "agency-code-reviewer", required: true }],
        approvers: [{ type: "agent", agent_id: approverId, agent_name_key: "agency-security-reviewer", required: true }],
        execution_policy: executionPolicy,
      }),
    }));
    const refreshed = await svc.getById(next!.id);
    expect(refreshed!.executionState).toMatchObject({
      hermesKanbanProjection: {
        managedFields: {
          reviewers: { owner: "fabric_manual_override", reverseSyncStatus: "accepted" },
          approvers: { owner: "fabric_manual_override", reverseSyncStatus: "accepted" },
          executionPolicy: { owner: "fabric_manual_override", reverseSyncStatus: "accepted" },
        },
      },
    });
  });

  it("serializes same-company user reviewers and approvers", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedUser(companyId, "Company Reviewer");
    const approverId = await seedUser(companyId, "Company Approver");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_user_governance", title: "User governance", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await svc.getById((await projectedIssueRow("t_reverse_user_governance")).id);
    const executionPolicy = {
      mode: "normal" as const,
      commentRequired: true,
      stages: [
        { id: randomUUID(), type: "review" as const, approvalsNeeded: 1 as const, participants: [{ type: "user" as const, userId: reviewerId }] },
        { id: randomUUID(), type: "approval" as const, approvalsNeeded: 1 as const, participants: [{ type: "user" as const, userId: approverId }] },
      ],
    };
    const next = await svc.update(previous!.id, { executionPolicy });
    const commandRunner = vi.fn(async () => ({ ok: true }));

    const result = await hermesKanbanReverseSyncService(db, { commandRunner })
      .syncCommittedIssueUpdate({
        previous: previous!,
        next: next!,
        actor: { actorType: "user", actorId: reviewerId },
      });

    expect(result.accepted).toBe(true);
    expect(commandRunner).toHaveBeenCalledWith(expect.objectContaining({
      patch: expect.objectContaining({
        reviewers: [{ type: "user", user_id: reviewerId, required: true }],
        approvers: [{ type: "user", user_id: approverId, required: true }],
        execution_policy: executionPolicy,
      }),
    }));
  });

  it("rejects cross-company and unknown user governance without a canonical payload", async () => {
    const companyId = await seedCompany("Origin Company");
    const otherCompanyId = await seedCompany("Other Company");
    const validUserId = await seedUser(companyId, "Valid Reviewer");
    const crossCompanyUserId = await seedUser(otherCompanyId, "Cross-company Reviewer");
    const unknownUserId = randomUUID();
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_invalid_users", title: "Invalid users", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const previous = await svc.getById((await projectedIssueRow("t_reverse_invalid_users")).id);

    const crossCompany = await svc.update(previous!.id, {
      executionPolicy: {
        mode: "normal",
        commentRequired: true,
        stages: [{
          id: randomUUID(),
          type: "review",
          approvalsNeeded: 1,
          participants: [{ type: "user", userId: crossCompanyUserId }],
        }],
      },
    });
    const crossCompanyRunner = vi.fn(async () => ({ ok: true }));
    const crossCompanyResult = await hermesKanbanReverseSyncService(db, { commandRunner: crossCompanyRunner })
      .syncCommittedIssueUpdate({
        previous: previous!,
        next: crossCompany!,
        actor: { actorType: "user", actorId: validUserId },
      });
    expect(crossCompanyResult.accepted).toBe(false);
    expect(crossCompanyResult.warning).toContain("active company-scoped user");
    expect(crossCompanyRunner).not.toHaveBeenCalled();

    const unknown = await svc.update(previous!.id, {
      executionPolicy: {
        mode: "normal",
        commentRequired: true,
        stages: [
          { id: randomUUID(), type: "review", approvalsNeeded: 1, participants: [{ type: "user", userId: validUserId }] },
          { id: randomUUID(), type: "approval", approvalsNeeded: 1, participants: [{ type: "user", userId: unknownUserId }] },
        ],
      },
    });
    const unknownRunner = vi.fn(async () => ({ ok: true }));
    const unknownResult = await hermesKanbanReverseSyncService(db, { commandRunner: unknownRunner })
      .syncCommittedIssueUpdate({
        previous: previous!,
        next: unknown!,
        actor: { actorType: "user", actorId: validUserId },
      });
    expect(unknownResult.accepted).toBe(false);
    expect(unknownResult.warning).toContain("active company-scoped user");
    expect(unknownRunner).not.toHaveBeenCalled();
    const refreshed = await svc.getById(previous!.id);
    expect(refreshed!.executionState).toMatchObject({
      hermesKanbanProjection: {
        reverseSyncFailed: expect.stringContaining("active company-scoped user"),
      },
    });
  });

  it("blocks reviewer removal and high-risk policy loosening pending authority", async () => {
    const companyId = await seedCompany();
    const reviewerId = await seedAgent(companyId, "agency-code-reviewer");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_loosen", title: "Reverse loosen", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const issue = await projectedIssueRow("t_reverse_loosen");
    const previous = await svc.update(issue.id, {
      executionPolicy: {
        mode: "normal",
        commentRequired: true,
        stages: [{ id: randomUUID(), type: "review", approvalsNeeded: 1, participants: [{ type: "agent", agentId: reviewerId }] }],
        authorizationPolicy: { production: "approval_required", secrets: "blocked" },
      },
    });
    const next = await svc.update(issue.id, {
      executionPolicy: { mode: "normal", commentRequired: true, stages: [] },
    });
    const commandRunner = vi.fn(async () => ({ ok: true }));
    const result = await hermesKanbanReverseSyncService(db, { commandRunner })
      .syncCommittedIssueUpdate({
        previous: previous!,
        next: next!,
        actor: { actorType: "user", actorId: "operator" },
      });
    expect(result.accepted).toBe(false);
    expect(result.warning).toContain("authority");
    expect(commandRunner).not.toHaveBeenCalled();
    const refreshed = await svc.getById(issue.id);
    expect(refreshed!.executionState).toMatchObject({
      hermesKanbanProjection: {
        reverseSyncFailed: expect.stringContaining("authority"),
        managedFields: {
          reviewers: { owner: "fabric_pending_reverse_sync", reverseSyncStatus: "failed" },
          executionPolicy: { owner: "fabric_pending_reverse_sync", reverseSyncStatus: "failed" },
        },
      },
    });
  });

  it("routes committed project edits through the CLI and records Fabric activity", async () => {
    const companyId = await seedCompany();
    const project = await seedProject(companyId, "Route Project");
    const { dir, dbPath } = seedKanbanDb({
      tasks: [{ id: "t_reverse_route", title: "Reverse route", status: "todo", priority: 50, createdAt: 1_782_827_060 }],
    });
    tempDirs.push(dir);
    process.env.FABRIC_HERMES_KANBAN_DB = dbPath;
    process.env.FABRIC_HERMES_KANBAN_COMPANY_ID = companyId;
    process.env.FABRIC_HERMES_KANBAN_BOARD = "agency-engineering";
    expect((await syncHermesKanbanIssues(db, companyId)).status).toBe("ok");
    const issue = await projectedIssueRow("t_reverse_route");
    const commandDir = mkdtempSync(join(tmpdir(), "fabric-reverse-cli-"));
    tempDirs.push(commandDir);
    const argsPath = join(commandDir, "args.txt");
    const cliPath = join(commandDir, "fake-hermes");
    writeFileSync(cliPath, `#!/bin/sh\nprintf '%s\\n' "$@" > ${JSON.stringify(argsPath)}\nprintf '{"ok":true}\\n'\n`);
    chmodSync(cliPath, 0o755);
    process.env.FABRIC_HERMES_CLI = cliPath;
    const app = express();
    app.use(express.json());
    app.use((req, _res, nextMiddleware) => {
      (req as any).actor = {
        type: "board",
        userId: "operator",
        companyIds: [companyId],
        memberships: [{ companyId, membershipRole: "admin", status: "active" }],
        source: "local_implicit",
      };
      nextMiddleware();
    });
    app.use("/api", issueRoutes(db, {} as any));
    app.use(errorHandler);

    const response = await request(app)
      .patch(`/api/issues/${issue.id}`)
      .send({ projectId: project.projectId });
    expect(response.status).toBe(200);
    const args = readFileSync(argsPath, "utf8").split("\n");
    expect(args).toEqual(expect.arrayContaining(["--board", "agency-engineering", "--db", dbPath]));
    const activities = await db.select({ action: activityLog.action, details: activityLog.details })
      .from(activityLog)
      .where(eq(activityLog.entityId, issue.id));
    expect(activities).toEqual(expect.arrayContaining([
      expect.objectContaining({
        action: "issue.hermes_reverse_sync_accepted",
        details: expect.objectContaining({ fields: ["projectId"], originId: "t_reverse_route" }),
      }),
    ]));
    delete process.env.FABRIC_HERMES_CLI;
    delete process.env.FABRIC_HERMES_KANBAN_BOARD;
  });
});
