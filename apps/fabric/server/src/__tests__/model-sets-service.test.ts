import { randomUUID } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { and, eq } from "drizzle-orm";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  agents,
  companies,
  costEvents,
  createDb,
  instanceSettings,
  modelDepartmentOverrides,
  modelPricing,
  modelProfileOverrides,
  modelSets,
} from "@paperclipai/db";
import { type ModelSetDefinition } from "@paperclipai/shared";
import {
  getEmbeddedPostgresTestSupport,
  startEmbeddedPostgresTestDatabase,
} from "./helpers/embedded-postgres.js";
import { modelSetService } from "../services/model-sets.ts";
import YAML from "yaml";

const embeddedPostgresSupport = await getEmbeddedPostgresTestSupport();
const describeEmbeddedPostgres = embeddedPostgresSupport.supported ? describe : describe.skip;

if (!embeddedPostgresSupport.supported) {
  console.warn(
    `Skipping embedded Postgres model set service tests on this host: ${embeddedPostgresSupport.reason ?? "unsupported environment"}`,
  );
}

function buildDefinition(name: string, provider = "openai", model = "gpt-5"): ModelSetDefinition {
  return {
    version: 1,
    name,
    defaults: { family: "general_worker" },
    families: {
      general_worker: { provider, model, reason: "default" },
    },
    profiles: {},
  };
}

describeEmbeddedPostgres("model set service", () => {
  let db!: ReturnType<typeof createDb>;
  let svc!: ReturnType<typeof modelSetService>;
  let tempDb: Awaited<ReturnType<typeof startEmbeddedPostgresTestDatabase>> | null = null;

  beforeAll(async () => {
    tempDb = await startEmbeddedPostgresTestDatabase("paperclip-model-sets-service-");
    db = createDb(tempDb.connectionString);
    svc = modelSetService(db);
  }, 20_000);

  afterEach(async () => {
    await db.delete(modelProfileOverrides);
    await db.delete(modelDepartmentOverrides);
    await db.delete(modelSets);
    await db.delete(instanceSettings);
    await db.delete(modelPricing);
    await db.delete(costEvents);
    await db.delete(agents);
    await db.delete(companies);
  });

  afterAll(async () => {
    await tempDb?.cleanup();
  });

  async function createCompanyAndAgent(prefix: string) {
    const companyId = randomUUID();
    const agentId = randomUUID();
    await db.insert(companies).values({
      id: companyId,
      name: `Model Set Company ${prefix}`,
      issuePrefix: prefix,
      requireBoardApprovalForNewAgents: false,
    });
    await db.insert(agents).values({
      id: agentId,
      companyId,
      name: `${prefix} Agent`,
      role: "engineer",
      status: "idle",
      adapterType: "hermes_local",
      adapterConfig: {},
    });
    return { companyId, agentId };
  }

  it("updates the active preference when renaming the active custom model set", async () => {
    const { companyId } = await createCompanyAndAgent(`MS${randomUUID().slice(0, 6).toUpperCase()}`);

    await svc.createModelSet(companyId, {
      definition: buildDefinition("custom-alpha"),
      createdBy: "creator-1",
    });
    await svc.applyModelSet(companyId, "custom-alpha", "creator-1");

    const renamed = await svc.updateModelSet(companyId, "custom-alpha", {
      definition: { name: "custom-beta" },
      updatedBy: "editor-1",
    });

    expect(renamed.name).toBe("custom-beta");
    expect(renamed.active).toBe(true);

    const active = await svc.getModelSet(companyId, "custom-beta");
    expect(active.active).toBe(true);

    const estimate = await svc.costEstimate(companyId);
    expect(estimate.activeModelSetName).toBe("custom-beta");
    expect(estimate.items).toHaveLength(1);
    expect(estimate.items[0]).toMatchObject({
      provider: "openai",
      model: "gpt-5",
      source: "model_set_default",
      setName: "custom-beta",
    });

    const settings = await db.select().from(instanceSettings).limit(1).then((rows) => rows[0]!);
    expect(settings.experimental).toMatchObject({
      modelSets: {
        activeByCompany: {
          [companyId]: "custom-beta",
        },
      },
    });
  });

  it("preserves created_by provenance when updating a model set", async () => {
    const { companyId } = await createCompanyAndAgent(`MP${randomUUID().slice(0, 6).toUpperCase()}`);

    const created = await svc.createModelSet(companyId, {
      definition: buildDefinition("custom-provenance"),
      createdBy: "creator-1",
    });

    const updated = await svc.updateModelSet(companyId, "custom-provenance", {
      description: "Edited description",
      updatedBy: "editor-2",
    });

    expect(updated.createdBy).toBe("creator-1");
    expect(updated.description).toBe("Edited description");
    expect(updated.updatedAt).toBeTruthy();

    const stored = await db
      .select()
      .from(modelSets)
      .where(and(eq(modelSets.companyId, companyId), eq(modelSets.name, "custom-provenance")))
      .limit(1)
      .then((rows) => rows[0]!);

    expect(stored.createdBy).toBe("creator-1");
    expect(stored.description).toBe("Edited description");
    expect(stored.updatedAt.getTime()).toBeGreaterThanOrEqual(created.updatedAt.getTime());
  });

  it("computes cost estimates across pricing types and historical fallback", async () => {
    const { companyId, agentId } = await createCompanyAndAgent(
      `MC${randomUUID().slice(0, 6).toUpperCase()}`,
    );

    await svc.createModelSet(companyId, {
      definition: buildDefinition("cost-set", "openrouter", "anthropic/claude-sonnet-4"),
      createdBy: "creator-1",
    });
    await svc.applyModelSet(companyId, "cost-set", "creator-1");

    await svc.upsertPricing([
      {
        provider: "openrouter",
        model: "anthropic/claude-sonnet-4",
        pricingType: "api",
        inputCostPer1m: 3,
        outputCostPer1m: 15,
        monthlyEstimate: null,
      },
      {
        provider: "local",
        model: "ollama/llama3",
        pricingType: "local",
        inputCostPer1m: null,
        outputCostPer1m: null,
        monthlyEstimate: null,
      },
    ]);

    await db.insert(costEvents).values({
      id: randomUUID(),
      companyId,
      agentId,
      provider: "openrouter",
      model: "anthropic/claude-sonnet-4",
      costCents: 1250,
      occurredAt: new Date(),
    });

    const estimate = await svc.costEstimate(companyId);
    expect(estimate.monthlyEstimateTotal).toBe(12.5);
    expect(estimate.unknownPricingCount).toBe(0);
    expect(estimate.items[0]).toMatchObject({
      agentId,
      monthlyEstimate: 12.5,
      estimateMethod: "historical",
      monthlyEstimateLabel: "$12.50",
      actualSpendLast30Days: 12.5,
    });

    const listed = await svc.listModelSets(companyId);
    const active = listed.find((row) => row.name === "cost-set");
    expect(active?.monthlyEstimateTotal).toBe(12.5);
    expect(active?.unknownPricingCount).toBe(0);
  });

  it("apply writes resolved models into Hermes profile config.yaml", async () => {
    const profilesDir = await mkdtemp(path.join(os.tmpdir(), "model-set-apply-profiles-"));
    const previous = process.env.HERMES_PROFILES_DIR;
    process.env.HERMES_PROFILES_DIR = profilesDir;
    try {
      const companyId = randomUUID();
      const agentId = randomUUID();
      await db.insert(companies).values({
        id: companyId,
        name: "Profile Apply Company",
        issuePrefix: "PA",
        requireBoardApprovalForNewAgents: false,
      });
      await db.insert(agents).values({
        id: agentId,
        companyId,
        name: "agency-backend-engineer",
        role: "engineer",
        status: "idle",
        adapterType: "hermes_local",
        adapterConfig: {},
      });

      await svc.createModelSet(companyId, {
        definition: buildDefinition("profile-apply-set", "openai", "gpt-5"),
        createdBy: "tester",
      });

      const result = await svc.applyModelSet(companyId, "profile-apply-set", { appliedBy: "tester" });
      expect(result.profileConfigs?.updated).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ profile: "agency-backend-engineer", provider: "openai", model: "gpt-5" }),
        ]),
      );

      const configPath = path.join(profilesDir, "agency-backend-engineer", "config.yaml");
      const parsed = YAML.parse(await readFile(configPath, "utf8")) as Record<string, unknown>;
      expect(parsed.model).toMatchObject({ provider: "openai", default: "gpt-5" });
    } finally {
      if (previous === undefined) delete process.env.HERMES_PROFILES_DIR;
      else process.env.HERMES_PROFILES_DIR = previous;
      await rm(profilesDir, { recursive: true, force: true });
    }
  });
});