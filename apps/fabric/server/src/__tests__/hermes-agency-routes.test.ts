import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import express from "express";
import os from "node:os";
import path from "node:path";
import request from "supertest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorHandler } from "../middleware/error-handler.js";
import { hermesAgencyRoutes } from "../routes/hermes-agency.js";

const tempDirs: string[] = [];

async function tempRosterPath(content: unknown) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "hermes-agency-roster-route-"));
  tempDirs.push(dir);
  const rosterPath = path.join(dir, "roster_state.json");
  await writeFile(rosterPath, JSON.stringify(content));
  return rosterPath;
}

function createApp(rosterPath: string, options: Record<string, unknown> = {}) {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = {
      type: "board",
      userId: "local-board",
      userName: "Local Board",
      userEmail: null,
      isInstanceAdmin: true,
      source: "local_implicit",
    };
    next();
  });
  app.use("/api/hermes-agency", hermesAgencyRoutes({ rosterPath, ...options }));
  app.use(errorHandler);
  return app;
}

function createNonAdminApp(rosterPath: string, options: Record<string, unknown> = {}) {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = {
      type: "board",
      userId: "company-member",
      companyIds: ["company-1"],
      memberships: [{ companyId: "company-1", status: "active", membershipRole: "member" }],
      isInstanceAdmin: false,
      source: "session",
    };
    next();
  });
  app.use("/api/hermes-agency", hermesAgencyRoutes({ rosterPath, ...options }));
  app.use(errorHandler);
  return app;
}

function createActorApp(rosterPath: string, actor: Record<string, unknown>, options: Record<string, unknown> = {}) {
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    (req as any).actor = actor;
    next();
  });
  app.use("/api/hermes-agency", hermesAgencyRoutes({ rosterPath, ...options }));
  app.use(errorHandler);
  return app;
}

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

it("rejects company members because Agency roster and dispatch storage are instance-global", async () => {
  const rosterPath = await tempRosterPath({ profiles: [] });

  const roster = await request(createNonAdminApp(rosterPath)).get("/api/hermes-agency/roster");
  const dispatch = await request(createNonAdminApp(rosterPath))
    .post("/api/hermes-agency/dispatch")
    .send({ packet: { title: "must not dispatch" } });

  expect(roster.status).toBe(403);
  expect(dispatch.status).toBe(403);
});

describe("Hermes Agency shared skill routes", () => {
  it("lets authenticated company members read the canonical filesystem pool but keeps mutations admin-only", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const root = path.dirname(rosterPath);
    const poolRoot = path.join(root, "pool");
    const profilesDir = path.join(root, "profiles");
    const skillDir = path.join(poolRoot, "newsjack", "breaking-news");
    const invalidSkillDir = path.join(poolRoot, "newsjack", "broken-yaml");
    await mkdir(skillDir, { recursive: true });
    await mkdir(invalidSkillDir, { recursive: true });
    await mkdir(profilesDir, { recursive: true });
    await writeFile(path.join(poolRoot, "pool-manifest.json"), JSON.stringify({ version: "1.0", categories: {} }));
    await writeFile(path.join(skillDir, "SKILL.md"), "---\nname: breaking-news\ndescription: React to news\n---\n");
    await writeFile(path.join(invalidSkillDir, "SKILL.md"), "---\nname: broken-yaml\ndescription: [unterminated\n---\n");

    const app = createNonAdminApp(rosterPath, { poolRoot, profilesDir, builtinSkillsDir: path.join(root, "builtin") });
    const listed = await request(app).get("/api/hermes-agency/shared-skills");
    const detail = await request(app).get("/api/hermes-agency/shared-skills/breaking-news");
    const created = await request(app).post("/api/hermes-agency/shared-skills").send({});

    expect(listed.status).toBe(200);
    expect(listed.body).toMatchObject({ canManage: false, skills: [
      expect.objectContaining({ name: "breaking-news", manifested: false, source: "shared_pool", valid: true, actionable: true }),
      expect.objectContaining({ name: "broken-yaml", valid: false, actionable: false, diagnostic: expect.objectContaining({ location: "newsjack/broken-yaml/SKILL.md" }) }),
    ] });
    expect(JSON.stringify(listed.body)).not.toContain(root);
    expect(detail.status).toBe(403);
    expect(created.status).toBe(403);
  });

  it("rejects agent keys from instance-global shared-skill source details", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const root = path.dirname(rosterPath);
    const poolRoot = path.join(root, "pool");
    const skillDir = path.join(poolRoot, "newsjack", "breaking-news");
    await mkdir(skillDir, { recursive: true });
    await writeFile(path.join(poolRoot, "pool-manifest.json"), JSON.stringify({ version: "1.0", categories: {} }));
    await writeFile(path.join(skillDir, "SKILL.md"), "---\nname: breaking-news\ndescription: React to news\n---\n");

    const actor = { type: "agent", source: "agent_key", agentId: "agent-1", companyId: "company-1" };
    const res = await request(createActorApp(rosterPath, actor, { poolRoot }))
      .get("/api/hermes-agency/shared-skills/breaking-news");

    expect(res.status).toBe(403);
  });

  it("redacts pre-existing credential-like text from admin detail responses", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const root = path.dirname(rosterPath);
    const poolRoot = path.join(root, "pool");
    const skillDir = path.join(poolRoot, "newsjack", "breaking-news");
    const credentialLikeText = "token=fixture_value_abcdefghijklmnop\n";
    await mkdir(path.join(skillDir, "scripts"), { recursive: true });
    await writeFile(path.join(poolRoot, "pool-manifest.json"), JSON.stringify({ version: "1.0", categories: {} }));
    await writeFile(path.join(skillDir, "SKILL.md"), "---\nname: breaking-news\ndescription: React to news\n---\n");
    await writeFile(path.join(skillDir, "scripts", "existing.py"), credentialLikeText);

    const res = await request(createApp(rosterPath, { poolRoot })).get("/api/hermes-agency/shared-skills/breaking-news");
    const updated = await request(createApp(rosterPath, { poolRoot }))
      .put("/api/hermes-agency/shared-skills/breaking-news")
      .send({ files: { "SKILL.md": "---\nname: breaking-news\ndescription: Updated safely\n---\n" } });

    expect(res.status).toBe(200);
    expect(JSON.stringify(res.body)).not.toContain(credentialLikeText.trim());
    expect(res.body.content).not.toHaveProperty("scripts/existing.py");
    expect(res.body.files).toContainEqual(expect.objectContaining({ path: "scripts/existing.py", editable: false }));
    expect(updated.status).toBe(200);
    expect(JSON.stringify(updated.body)).not.toContain(credentialLikeText.trim());
    expect(await readFile(path.join(skillDir, "scripts", "existing.py"), "utf8")).toBe(credentialLikeText);
  });

  it("requires authentication for shared-pool reads", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const res = await request(createActorApp(rosterPath, { type: "none", source: "none" }))
      .get("/api/hermes-agency/shared-skills");
    expect(res.status).toBe(401);
  });
  it("rejects cross-company agent profile access before filesystem resolution", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const db = {
      select: () => ({ from: () => ({ where: () => Promise.resolve([{ id: "agent-2", name: "agency-target", companyId: "company-2", adapterConfig: { hermesProfile: "agency-target" } }]) }) }),
    };
    const actor = { type: "agent", source: "agent_key", agentId: "agent-1", companyId: "company-1" };
    const res = await request(createActorApp(rosterPath, actor, { db: db as never }))
      .get("/api/hermes-agency/agents/agent-2/skills");
    expect(res.status).toBe(403);
  });
});

describe("Hermes Agency roster route", () => {
  it("returns a stable roster response shape", async () => {
    const rosterPath = await tempRosterPath({
      profiles: [
        {
          name: "agency-backend-engineer",
          description: "Builds APIs",
          skills: ["api", "database"],
          online: false,
          wake_attempt_count: 1,
          last_wake_error: "Error: profile agency-backend-engineer not found",
          model: "gpt-5.5",
          provider: "openai-codex",
        },
      ],
    });

    const res = await request(createApp(rosterPath)).get("/api/hermes-agency/roster");

    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      tenant: "default",
      filter: "agency-only",
      total: 1,
      online: 0,
      offline: 1,
      agents: [
        {
          name: "agency-backend-engineer",
          description: "Builds APIs",
          skills: ["api", "database"],
          online: false,
          status: "wake_failed",
          wakeAttempts: 1,
          lastError: "Error: profile agency-backend-engineer not found",
          model: "gpt-5.5",
          provider: "openai-codex",
        },
      ],
    });
  });

  it("returns 503 when the roster source is unavailable", async () => {
    const res = await request(createApp("/tmp/does-not-exist/hermes-agency-roster.json"))
      .get("/api/hermes-agency/roster");

    expect(res.status).toBe(503);
    expect(res.body.error).toBe("hermes_agency_roster_unavailable");
  });

  it("previews an Agency task packet without dispatching", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });

    const res = await request(createApp(rosterPath))
      .post("/api/hermes-agency/task-packet-preview")
      .send({
        issue: {
          id: "issue-1",
          identifier: "HF-43",
          title: "Map tasks to Agency packets",
          description: "Create a read-only preview for Hermes Agency dispatch packets.",
          priority: "high",
          labels: [{ name: "backend" }],
          currentExecutionWorkspace: {
            name: "Hermes_Fabric",
            rootPath: "/workspace/hermes-fabric",
          },
        },
        requestedSkills: ["api", "typescript"],
      });

    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({
      dispatchReady: false,
      dispatchMode: "skill-fit",
      title: "[HF-43] Map tasks to Agency packets",
      targetAgentName: null,
      requestedSkills: ["api", "typescript", "backend"],
    });
    expect(res.body.context).toContain("Workspace root: /workspace/hermes-fabric");
  });

  it("dispatches skill-fit packets first and persists queued wake failures", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const dispatchStorePath = path.join(path.dirname(rosterPath), "dispatches.json");
    const dispatchClient = {
      dispatch: vi.fn(async () => ({
        status: "queued",
        queueId: "offline-queue-1",
        taskId: null,
        message: "queued after wake failure",
        raw: { last_error: "profile agency-backend-engineer not found" },
      })),
    };

    const res = await request(createApp(rosterPath, { dispatchStorePath, dispatchClient }))
      .post("/api/hermes-agency/dispatch")
      .send({
        packet: {
          title: "[HF-44] Dispatch through skill fit",
          goal: "Send a harmless planning task through skill fit.",
          context: "Test context",
          requestedSkills: ["api", "typescript"],
          targetAgentName: "agency-backend-engineer",
          dispatchMode: "direct-agent",
          routing: { mode: "direct-agent", rationale: "Direct target selected" },
          workspaceContext: {},
          validationExpectations: ["Run targeted tests"],
          artifactExpectations: ["Report results"],
          stopConditions: ["Stop if blocked"],
          dispatchReady: false,
        },
        mode: "skill-fit",
      });

    expect(res.status).toBe(202);
    expect(dispatchClient.dispatch).toHaveBeenCalledWith(expect.objectContaining({
      mode: "skill-fit",
      skill: "api",
      targetAgentName: null,
    }));
    expect(res.body).toMatchObject({
      mode: "skill-fit",
      status: "queued",
      queueId: "offline-queue-1",
      taskId: null,
      statusHistory: [{ status: "queued" }],
    });

    const statusRes = await request(createApp(rosterPath, { dispatchStorePath, dispatchClient }))
      .get(`/api/hermes-agency/dispatches/${res.body.id}`);
    expect(statusRes.status).toBe(200);
    expect(statusRes.body.queueId).toBe("offline-queue-1");
  });

  it("dispatches direct-agent packets and records completed artifacts", async () => {
    const rosterPath = await tempRosterPath({ profiles: [] });
    const dispatchStorePath = path.join(path.dirname(rosterPath), "direct-dispatches.json");
    const dispatchClient = {
      dispatch: vi.fn(async () => ({
        status: "completed",
        queueId: null,
        taskId: "task-123",
        message: "completed",
        artifacts: [{ type: "text", text: "done" }],
        raw: { artifact_text: "done" },
      })),
    };

    const res = await request(createApp(rosterPath, { dispatchStorePath, dispatchClient }))
      .post("/api/hermes-agency/dispatch")
      .send({
        packet: {
          title: "[HF-45] Dispatch direct",
          goal: "Send a harmless direct task.",
          context: "Test context",
          requestedSkills: ["api"],
          targetAgentName: "agency-backend-engineer",
          dispatchMode: "direct-agent",
          routing: { mode: "direct-agent", rationale: "Direct target selected" },
          workspaceContext: {},
          validationExpectations: [],
          artifactExpectations: [],
          stopConditions: [],
          dispatchReady: false,
        },
        mode: "direct-agent",
      });

    expect(res.status).toBe(202);
    expect(dispatchClient.dispatch).toHaveBeenCalledWith(expect.objectContaining({
      mode: "direct-agent",
      targetAgentName: "agency-backend-engineer",
    }));
    expect(res.body).toMatchObject({
      status: "completed",
      taskId: "task-123",
      artifacts: [{ type: "text", text: "done" }],
      statusHistory: [{ status: "completed" }],
    });
  });
});
