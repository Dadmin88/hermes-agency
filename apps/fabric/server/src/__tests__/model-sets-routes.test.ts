import express from "express";
import request from "supertest";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockModelSetService = vi.hoisted(() => ({
  listModelSets: vi.fn(),
  getModelSet: vi.fn(),
  createModelSet: vi.fn(),
  updateModelSet: vi.fn(),
  deleteModelSet: vi.fn(),
  previewApply: vi.fn(),
  applyModelSet: vi.fn(),
  listDepartmentOverrides: vi.fn(),
  replaceDepartmentOverrides: vi.fn(),
  listProfileOverrides: vi.fn(),
  upsertProfileOverride: vi.fn(),
  deleteProfileOverride: vi.fn(),
  listPricing: vi.fn(),
  upsertPricing: vi.fn(),
  costEstimate: vi.fn(),
}));
const mockLogActivity = vi.hoisted(() => vi.fn());

function registerModuleMocks() {
  vi.doMock("../services/index.js", () => ({
    modelSetService: () => mockModelSetService,
    logActivity: mockLogActivity,
  }));
}

async function createApp(actor: any) {
  const [{ errorHandler }, { modelSetRoutes }] = await Promise.all([
    vi.importActual<typeof import("../middleware/index.js")>("../middleware/index.js"),
    vi.importActual<typeof import("../routes/model-sets.js")>("../routes/model-sets.js"),
  ]);
  const app = express();
  app.use(express.json());
  app.use((req, _res, next) => {
    req.actor = actor;
    next();
  });
  app.use("/api", modelSetRoutes({} as any));
  app.use(errorHandler);
  return app;
}

describe("model set routes", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.doUnmock("../services/index.js");
    vi.doUnmock("../routes/model-sets.js");
    vi.doUnmock("../routes/authz.js");
    vi.doUnmock("../middleware/index.js");
    registerModuleMocks();
    vi.clearAllMocks();
    Object.values(mockModelSetService).forEach((fn) => fn.mockReset());
    mockLogActivity.mockReset();

    mockModelSetService.listModelSets.mockResolvedValue([
      { name: "balanced", source: "packaged", active: true },
      { name: "custom-alpha", source: "custom", active: false },
    ]);
    mockModelSetService.getModelSet.mockResolvedValue({
      id: "packaged:balanced",
      name: "balanced",
      source: "packaged",
      active: true,
      definition: { families: {}, profiles: {}, defaults: { family: "general_worker" } },
    });
    mockModelSetService.createModelSet.mockResolvedValue({
      id: "custom-1",
      name: "custom-alpha",
      source: "custom",
      active: false,
    });
    mockModelSetService.updateModelSet.mockResolvedValue({
      id: "custom-1",
      name: "custom-alpha",
      source: "custom",
      active: false,
    });
    mockModelSetService.deleteModelSet.mockResolvedValue({ deleted: true, name: "custom-alpha" });
    mockModelSetService.previewApply.mockResolvedValue({
      companyId: "11111111-1111-4111-8111-111111111111",
      name: "balanced",
      changes: [{ agentId: "agent-1" }],
    });
    mockModelSetService.applyModelSet.mockResolvedValue({
      applied: true,
      name: "balanced",
      changedAgents: 1,
    });
    mockModelSetService.listDepartmentOverrides.mockResolvedValue([
      { department: "engineer", provider: "openai", model: "gpt-5" },
    ]);
    mockModelSetService.replaceDepartmentOverrides.mockResolvedValue([
      { department: "engineer", provider: "openai", model: "gpt-5" },
    ]);
    mockModelSetService.listProfileOverrides.mockResolvedValue([
      { agentId: "agent-1", agentName: "Backend", provider: "openai", model: "gpt-5" },
    ]);
    mockModelSetService.upsertProfileOverride.mockResolvedValue({
      agentId: "agent-1",
      provider: "openai",
      model: "gpt-5",
    });
    mockModelSetService.deleteProfileOverride.mockResolvedValue({ deleted: true, agentId: "agent-1" });
    mockModelSetService.listPricing.mockResolvedValue([
      { provider: "openai", model: "gpt-5", pricingType: "api" },
    ]);
    mockModelSetService.upsertPricing.mockResolvedValue([
      { provider: "openai", model: "gpt-5", pricingType: "api" },
    ]);
    mockModelSetService.costEstimate.mockResolvedValue({
      companyId: "11111111-1111-4111-8111-111111111111",
      itemCount: 1,
      monthlyEstimateTotal: 42,
      items: [],
    });
  });

  const actor = {
    type: "board",
    userId: "user-1",
    source: "session",
    isInstanceAdmin: false,
    companyIds: ["11111111-1111-4111-8111-111111111111"],
    memberships: [
      {
        companyId: "11111111-1111-4111-8111-111111111111",
        status: "active",
        membershipRole: "editor",
      },
    ],
  };

  it("lists model sets for a company", async () => {
    const app = await createApp(actor);
    const res = await request(app)
      .get("/api/model-sets")
      .query({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(200);

    expect(res.body).toHaveLength(2);
    expect(mockModelSetService.listModelSets).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  it("creates a custom model set and logs activity", async () => {
    const app = await createApp(actor);
    const res = await request(app)
      .post("/api/model-sets")
      .send({
        companyId: "11111111-1111-4111-8111-111111111111",
        definition: {
          version: 1,
          name: "custom-alpha",
          defaults: { family: "general_worker" },
          families: {
            general_worker: { provider: "openai", model: "gpt-5", reason: "default" },
          },
          profiles: {},
        },
      })
      .expect(201);

    expect(res.body.name).toBe("custom-alpha");
    expect(mockModelSetService.createModelSet).toHaveBeenCalled();
    expect(mockLogActivity).toHaveBeenCalledTimes(1);
  });

  it("previews and applies a model set", async () => {
    const app = await createApp(actor);
    await request(app)
      .get("/api/model-sets/balanced/preview")
      .query({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(200);
    await request(app)
      .post("/api/model-sets/balanced/apply")
      .send({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(200);

    expect(mockModelSetService.previewApply).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
      "balanced",
    );
    expect(mockModelSetService.applyModelSet).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
      "balanced",
      "user-1",
    );
  });

  it("manages department and profile overrides", async () => {
    const app = await createApp(actor);
    await request(app)
      .put("/api/model-overrides/department")
      .send({
        companyId: "11111111-1111-4111-8111-111111111111",
        overrides: [{ department: "engineer", provider: "openai", model: "gpt-5" }],
      })
      .expect(200);
    await request(app)
      .put("/api/model-overrides/profile/agent-1")
      .send({
        companyId: "11111111-1111-4111-8111-111111111111",
        provider: "openai",
        model: "gpt-5",
      })
      .expect(200);
    await request(app)
      .delete("/api/model-overrides/profile/agent-1")
      .query({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(200);

    expect(mockModelSetService.replaceDepartmentOverrides).toHaveBeenCalled();
    expect(mockModelSetService.upsertProfileOverride).toHaveBeenCalled();
    expect(mockModelSetService.deleteProfileOverride).toHaveBeenCalled();
  });

  it("lists pricing and cost estimates", async () => {
    const app = await createApp(actor);
    await request(app).get("/api/model-pricing").expect(200);
    await request(app)
      .put("/api/model-pricing")
      .send({
        items: [{ provider: "openai", model: "gpt-5", pricingType: "api" }],
      })
      .expect(200);
    const res = await request(app)
      .get("/api/model-cost-estimate")
      .query({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(200);

    expect(res.body.monthlyEstimateTotal).toBe(42);
    expect(mockModelSetService.listPricing).toHaveBeenCalled();
    expect(mockModelSetService.costEstimate).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
    );
  });

  it("rejects users without company access", async () => {
    const app = await createApp({
      ...actor,
      companyIds: [],
    });
    await request(app)
      .get("/api/model-sets")
      .query({ companyId: "11111111-1111-4111-8111-111111111111" })
      .expect(403);
    expect(mockModelSetService.listModelSets).not.toHaveBeenCalled();
  });
});
