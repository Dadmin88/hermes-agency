import { mkdtemp, rm, writeFile } from "node:fs/promises";
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

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
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
