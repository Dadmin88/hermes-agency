import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { and, asc, eq } from "drizzle-orm";
import {
  agents,
  instanceSettings,
  modelDepartmentOverrides,
  modelPricing,
  modelProfileOverrides,
  modelSets,
  type Db,
} from "@paperclipai/db";
import {
  modelSetDefinitionSchema,
  type ModelDepartmentOverrideInput,
  type ModelPricingItem,
  type ModelSetDefinition,
  type ModelSetDefinitionPatch,
} from "@paperclipai/shared";
import { conflict, notFound, unprocessable } from "../errors.js";
import YAML from "yaml";

type PackagedModelSetMap = Map<string, ModelSetRecord>;

type ModelResolution = {
  provider: string;
  model: string;
  source:
    | "profile_override"
    | "department_override"
    | "model_set_profile"
    | "model_set_default"
    | "global_default"
    | "none";
  setName: string | null;
  family: string | null;
  reason: string | null;
};

type ModelSetRecord = {
  id: string;
  companyId: string | null;
  name: string;
  description: string | null;
  source: "custom" | "packaged";
  definition: ModelSetDefinition;
  createdBy: string | null;
  createdAt: Date | null;
  updatedAt: Date | null;
};

type ModelSetPreferences = {
  activeByCompany: Record<string, string>;
  globalDefaultName: string | null;
};

type SettingsDb = Pick<Db, "select" | "update" | "insert">;

const packagedModelSetsDir =
  process.env.PAPERCLIP_MODEL_SETS_DIR?.trim() ||
  fileURLToPath(new URL("../../../../../hermes-agency/model_sets", import.meta.url));

let packagedCache: Promise<PackagedModelSetMap> | null = null;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function toNullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function normalizeName(value: string): string {
  return value.trim();
}

function deepMergeModelSetDefinition(
  current: ModelSetDefinition,
  patch: ModelSetDefinitionPatch,
): ModelSetDefinition {
  const merged = {
    ...current,
    ...patch,
    description:
      patch.description === undefined
        ? current.description
        : patch.description === null
          ? undefined
          : patch.description,
    defaults: patch.defaults ? { ...current.defaults, ...patch.defaults } : current.defaults,
    families: patch.families ? { ...current.families, ...patch.families } : current.families,
    profiles: patch.profiles ? { ...current.profiles, ...patch.profiles } : current.profiles,
    escalation: patch.escalation
      ? {
          ...(current.escalation ?? {}),
          ...patch.escalation,
          triggers: patch.escalation.triggers ?? current.escalation?.triggers ?? [],
        }
      : current.escalation,
    budget: patch.budget ? { ...(current.budget ?? {}), ...patch.budget } : current.budget,
    metadata: patch.metadata ? { ...(current.metadata ?? {}), ...patch.metadata } : current.metadata,
  };
  return modelSetDefinitionSchema.parse(merged);
}

async function loadPackagedModelSets(): Promise<PackagedModelSetMap> {
  if (!packagedCache) {
    packagedCache = (async () => {
      const entries = await readdir(packagedModelSetsDir, { withFileTypes: true });
      const files = entries
        .filter((entry) => entry.isFile() && /\.ya?ml$/i.test(entry.name))
        .sort((a, b) => a.name.localeCompare(b.name));
      const result = new Map<string, ModelSetRecord>();
      for (const file of files) {
        const fullPath = path.join(packagedModelSetsDir, file.name);
        const parsed = YAML.parse(await readFile(fullPath, "utf8"));
        const definition = modelSetDefinitionSchema.parse(parsed);
        result.set(definition.name, {
          id: `packaged:${definition.name}`,
          companyId: null,
          name: definition.name,
          description: definition.description ?? null,
          source: "packaged",
          definition,
          createdBy: "packaged",
          createdAt: null,
          updatedAt: null,
        });
      }
      return result;
    })();
  }
  return packagedCache;
}

export function resetPackagedModelSetCacheForTests() {
  packagedCache = null;
}

function buildModelSetPreferences(rawExperimental: unknown): ModelSetPreferences {
  const experimental = asRecord(rawExperimental);
  const modelSetsNode = asRecord(experimental.modelSets);
  const activeByCompanyNode = asRecord(modelSetsNode.activeByCompany);
  const activeByCompany: Record<string, string> = {};
  for (const [companyId, name] of Object.entries(activeByCompanyNode)) {
    if (typeof name === "string" && name.trim().length > 0) {
      activeByCompany[companyId] = name.trim();
    }
  }
  return {
    activeByCompany,
    globalDefaultName: toNullableString(modelSetsNode.globalDefaultName),
  };
}

function buildExperimentalWithPreferences(
  rawExperimental: unknown,
  preferences: ModelSetPreferences,
): Record<string, unknown> {
  const experimental = asRecord(rawExperimental);
  const current = asRecord(experimental.modelSets);
  return {
    ...experimental,
    modelSets: {
      ...current,
      activeByCompany: preferences.activeByCompany,
      globalDefaultName: preferences.globalDefaultName,
    },
  };
}

function getFamilyForAgent(definition: ModelSetDefinition, agentName: string): string | null {
  const profileFamily = definition.profiles[agentName];
  if (profileFamily && definition.families[profileFamily]) {
    return profileFamily;
  }
  return definition.defaults.family in definition.families ? definition.defaults.family : null;
}

function splitProviderModel(modelId: string): { provider: string; model: string } | null {
  const trimmed = modelId.trim();
  const slashIndex = trimmed.indexOf("/");
  if (slashIndex <= 0 || slashIndex === trimmed.length - 1) return null;
  return {
    provider: trimmed.slice(0, slashIndex),
    model: trimmed.slice(slashIndex + 1),
  };
}

function buildResolvedAdapterConfig(
  adapterType: string,
  adapterConfig: Record<string, unknown>,
  provider: string,
  model: string,
): Record<string, unknown> {
  if (adapterType === "opencode_local" || adapterType === "pi_local") {
    return {
      ...adapterConfig,
      model: `${provider}/${model}`,
    };
  }
  if (adapterType === "hermes_local" || adapterType === "hermes_gateway") {
    return {
      ...adapterConfig,
      provider,
      model,
    };
  }
  return {
    ...adapterConfig,
    provider,
    model,
  };
}

async function getInstanceSettingsRow(db: SettingsDb) {
  const [row] = await db.select().from(instanceSettings).limit(1);
  return row ?? null;
}

async function upsertInstanceExperimentalSettings(db: SettingsDb, experimental: Record<string, unknown>) {
  const existing = await getInstanceSettingsRow(db);
  if (existing) {
    const [updated] = await db
      .update(instanceSettings)
      .set({ experimental, updatedAt: new Date() })
      .where(eq(instanceSettings.id, existing.id))
      .returning();
    return updated;
  }
  const [created] = await db
    .insert(instanceSettings)
    .values({
      singletonKey: "default",
      general: {},
      experimental,
      createdAt: new Date(),
      updatedAt: new Date(),
    })
    .returning();
  return created;
}

export function modelSetService(db: Db) {
  async function listCustomModelSets(companyId: string): Promise<ModelSetRecord[]> {
    const rows = await db
      .select()
      .from(modelSets)
      .where(eq(modelSets.companyId, companyId))
      .orderBy(asc(modelSets.name));
    return rows.map((row) => ({
      id: row.id,
      companyId: row.companyId,
      name: row.name,
      description: row.description,
      source: row.source === "packaged" ? "packaged" : "custom",
      definition: modelSetDefinitionSchema.parse(row.definition),
      createdBy: row.createdBy,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    }));
  }

  async function getPreferences() {
    const row = await getInstanceSettingsRow(db);
    return buildModelSetPreferences(row?.experimental ?? {});
  }

  async function getActiveModelSetName(companyId: string): Promise<string | null> {
    const preferences = await getPreferences();
    return preferences.activeByCompany[companyId] ?? preferences.globalDefaultName ?? null;
  }

  async function getModelSetRecord(companyId: string, name: string): Promise<ModelSetRecord> {
    const normalizedName = normalizeName(name);
    const packaged = await loadPackagedModelSets();
    const packagedRecord = packaged.get(normalizedName);
    if (packagedRecord) return packagedRecord;

    const [row] = await db
      .select()
      .from(modelSets)
      .where(and(eq(modelSets.companyId, companyId), eq(modelSets.name, normalizedName)))
      .limit(1);
    if (!row) {
      throw notFound(`Model set "${normalizedName}" not found.`);
    }
    return {
      id: row.id,
      companyId: row.companyId,
      name: row.name,
      description: row.description,
      source: row.source === "packaged" ? "packaged" : "custom",
      definition: modelSetDefinitionSchema.parse(row.definition),
      createdBy: row.createdBy,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    };
  }

  async function getDepartmentOverrideMap(companyId: string) {
    const rows = await db
      .select()
      .from(modelDepartmentOverrides)
      .where(eq(modelDepartmentOverrides.companyId, companyId));
    return new Map(rows.map((row) => [row.department, row]));
  }

  async function getProfileOverrideMap(companyId: string) {
    const rows = await db
      .select()
      .from(modelProfileOverrides)
      .where(eq(modelProfileOverrides.companyId, companyId));
    return new Map(rows.map((row) => [row.agentId, row]));
  }

  async function resolveAgentModel(
    companyId: string,
    agent: typeof agents.$inferSelect,
    activeSet: ModelSetRecord | null,
    departmentOverrideMap?: Map<string, typeof modelDepartmentOverrides.$inferSelect>,
    profileOverrideMap?: Map<string, typeof modelProfileOverrides.$inferSelect>,
  ): Promise<ModelResolution> {
    const profileOverrides = profileOverrideMap ?? (await getProfileOverrideMap(companyId));
    const profileOverride = profileOverrides.get(agent.id);
    if (profileOverride) {
      return {
        provider: profileOverride.provider,
        model: profileOverride.model,
        source: "profile_override",
        setName: activeSet?.name ?? null,
        family: null,
        reason: profileOverride.reason ?? null,
      };
    }

    const departmentOverrides =
      departmentOverrideMap ?? (await getDepartmentOverrideMap(companyId));
    const departmentOverride = departmentOverrides.get(agent.role);
    if (departmentOverride) {
      return {
        provider: departmentOverride.provider,
        model: departmentOverride.model,
        source: "department_override",
        setName: activeSet?.name ?? null,
        family: null,
        reason: departmentOverride.reason ?? null,
      };
    }

    if (activeSet) {
      const familyName = getFamilyForAgent(activeSet.definition, agent.name);
      if (familyName) {
        const family = activeSet.definition.families[familyName];
        if (family) {
          return {
            provider: family.provider,
            model: family.model,
            source:
              activeSet.definition.profiles[agent.name] && activeSet.definition.profiles[agent.name] === familyName
                ? "model_set_profile"
                : "model_set_default",
            setName: activeSet.name,
            family: familyName,
            reason: family.reason ?? null,
          };
        }
      }
    }

    const currentConfig = asRecord(agent.adapterConfig);
    const provider = toNullableString(currentConfig.provider);
    const model = toNullableString(currentConfig.model);
    if (provider && model) {
      return {
        provider,
        model,
        source: "global_default",
        setName: activeSet?.name ?? null,
        family: null,
        reason: null,
      };
    }

    if (model) {
      const parsed = splitProviderModel(model);
      if (parsed) {
        return {
          provider: parsed.provider,
          model: parsed.model,
          source: "global_default",
          setName: activeSet?.name ?? null,
          family: null,
          reason: null,
        };
      }
    }

    return {
      provider: "",
      model: "",
      source: "none",
      setName: activeSet?.name ?? null,
      family: null,
      reason: null,
    };
  }

  return {
    listModelSets: async (companyId: string) => {
      const [packaged, custom, activeName] = await Promise.all([
        loadPackagedModelSets(),
        listCustomModelSets(companyId),
        getActiveModelSetName(companyId),
      ]);
      const records = [...Array.from(packaged.values()), ...custom].sort((a, b) =>
        a.name.localeCompare(b.name),
      );
      return records.map((record) => ({
        id: record.id,
        companyId: record.companyId,
        name: record.name,
        description: record.description,
        source: record.source,
        active: activeName === record.name,
        familyCount: Object.keys(record.definition.families).length,
        profileCount: Object.keys(record.definition.profiles).length,
        createdBy: record.createdBy,
        createdAt: record.createdAt,
        updatedAt: record.updatedAt,
      }));
    },

    getModelSet: async (companyId: string, name: string) => {
      const [record, activeName] = await Promise.all([
        getModelSetRecord(companyId, name),
        getActiveModelSetName(companyId),
      ]);
      return {
        id: record.id,
        companyId: record.companyId,
        name: record.name,
        description: record.description,
        source: record.source,
        active: activeName === record.name,
        definition: record.definition,
        createdBy: record.createdBy,
        createdAt: record.createdAt,
        updatedAt: record.updatedAt,
      };
    },

    createModelSet: async (
      companyId: string,
      input: { definition: ModelSetDefinition; description?: string | null; createdBy?: string | null },
    ) => {
      const definition = modelSetDefinitionSchema.parse(input.definition);
      const name = normalizeName(definition.name);
      const packaged = await loadPackagedModelSets();
      if (packaged.has(name)) {
        throw conflict(`Model set "${name}" already exists as a packaged model set.`);
      }
      const existing = await db
        .select({ id: modelSets.id })
        .from(modelSets)
        .where(and(eq(modelSets.companyId, companyId), eq(modelSets.name, name)))
        .limit(1);
      if (existing.length > 0) {
        throw conflict(`Model set "${name}" already exists for this company.`);
      }
      const now = new Date();
      const [created] = await db
        .insert(modelSets)
        .values({
          companyId,
          name,
          description: input.description ?? definition.description ?? null,
          source: "custom",
          definition,
          createdBy: input.createdBy ?? "system",
          createdAt: now,
          updatedAt: now,
        })
        .returning();
      return {
        id: created.id,
        companyId: created.companyId,
        name: created.name,
        description: created.description,
        source: "custom" as const,
        active: false,
        definition: modelSetDefinitionSchema.parse(created.definition),
        createdBy: created.createdBy,
        createdAt: created.createdAt,
        updatedAt: created.updatedAt,
      };
    },

    updateModelSet: async (
      companyId: string,
      name: string,
      input: { definition?: ModelSetDefinitionPatch; description?: string | null; updatedBy?: string | null },
    ) => {
      const updated = await db.transaction(async (tx) => {
        const normalizedName = normalizeName(name);
        const packaged = await loadPackagedModelSets();
        if (packaged.has(normalizedName)) {
          throw unprocessable("Packaged model sets cannot be edited.");
        }

        const [row] = await tx
          .select()
          .from(modelSets)
          .where(and(eq(modelSets.companyId, companyId), eq(modelSets.name, normalizedName)))
          .limit(1);
        if (!row) {
          throw notFound(`Model set "${normalizedName}" not found.`);
        }

        const record: ModelSetRecord = {
          id: row.id,
          companyId: row.companyId,
          name: row.name,
          description: row.description,
          source: row.source === "packaged" ? "packaged" : "custom",
          definition: modelSetDefinitionSchema.parse(row.definition),
          createdBy: row.createdBy,
          createdAt: row.createdAt,
          updatedAt: row.updatedAt,
        };

        const nextDefinition = input.definition
          ? deepMergeModelSetDefinition(record.definition, input.definition)
          : record.definition;
        const nextName = normalizeName(nextDefinition.name);
        if (nextName !== record.name) {
          const duplicate = await tx
            .select({ id: modelSets.id })
            .from(modelSets)
            .where(and(eq(modelSets.companyId, companyId), eq(modelSets.name, nextName)))
            .limit(1);
          if (duplicate.length > 0) {
            throw conflict(`Model set "${nextName}" already exists for this company.`);
          }
        }

        const settingsRow = await getInstanceSettingsRow(tx);
        const preferences = buildModelSetPreferences(settingsRow?.experimental ?? {});
        const renamedActivePreference =
          nextName !== record.name && preferences.activeByCompany[companyId] === record.name;

        const [updatedRecord] = await tx
          .update(modelSets)
          .set({
            name: nextName,
            description:
              input.description === undefined
                ? nextDefinition.description ?? record.description
                : input.description,
            definition: nextDefinition,
            createdBy: record.createdBy ?? "system",
            updatedAt: new Date(),
          })
          .where(and(eq(modelSets.companyId, companyId), eq(modelSets.id, record.id)))
          .returning();

        if (renamedActivePreference) {
          preferences.activeByCompany[companyId] = nextName;
          await upsertInstanceExperimentalSettings(
            tx,
            buildExperimentalWithPreferences(settingsRow?.experimental ?? {}, preferences),
          );
        }

        return updatedRecord;
      });
      const activeName = await getActiveModelSetName(companyId);
      return {
        id: updated.id,
        companyId: updated.companyId,
        name: updated.name,
        description: updated.description,
        source: "custom" as const,
        active: activeName === updated.name,
        definition: modelSetDefinitionSchema.parse(updated.definition),
        createdBy: updated.createdBy,
        createdAt: updated.createdAt,
        updatedAt: updated.updatedAt,
      };
    },

    deleteModelSet: async (companyId: string, name: string) => {
      const record = await getModelSetRecord(companyId, name);
      if (record.source !== "custom") {
        throw unprocessable("Packaged model sets cannot be deleted.");
      }
      await db
        .delete(modelSets)
        .where(and(eq(modelSets.companyId, companyId), eq(modelSets.id, record.id)));

      const settingsRow = await getInstanceSettingsRow(db);
      const preferences = buildModelSetPreferences(settingsRow?.experimental ?? {});
      if (preferences.activeByCompany[companyId] === record.name) {
        delete preferences.activeByCompany[companyId];
        await upsertInstanceExperimentalSettings(
          db,
          buildExperimentalWithPreferences(settingsRow?.experimental ?? {}, preferences),
        );
      }
      return { deleted: true, name: record.name };
    },

    previewApply: async (companyId: string, name: string) => {
      const [record, agentRows, departmentOverrideMap, profileOverrideMap] = await Promise.all([
        getModelSetRecord(companyId, name),
        db.select().from(agents).where(eq(agents.companyId, companyId)).orderBy(asc(agents.name)),
        getDepartmentOverrideMap(companyId),
        getProfileOverrideMap(companyId),
      ]);
      const changes = [] as Array<{
        agentId: string;
        agentName: string;
        adapterType: string;
        before: { provider: string | null; model: string | null };
        after: { provider: string; model: string };
        family: string | null;
        source: ModelResolution["source"];
      }>;
      for (const agentRow of agentRows) {
        const resolution = await resolveAgentModel(
          companyId,
          agentRow,
          record,
          departmentOverrideMap,
          profileOverrideMap,
        );
        if (resolution.source === "none") continue;
        const current = asRecord(agentRow.adapterConfig);
        const currentProvider = toNullableString(current.provider);
        const currentModelValue = toNullableString(current.model);
        const currentModel =
          currentProvider || !currentModelValue
            ? currentModelValue
            : splitProviderModel(currentModelValue)?.model ?? currentModelValue;
        if (currentProvider === resolution.provider && currentModel === resolution.model) {
          continue;
        }
        changes.push({
          agentId: agentRow.id,
          agentName: agentRow.name,
          adapterType: agentRow.adapterType,
          before: { provider: currentProvider, model: currentModelValue },
          after: { provider: resolution.provider, model: resolution.model },
          family: resolution.family,
          source: resolution.source,
        });
      }
      return {
        companyId,
        name: record.name,
        source: record.source,
        changes,
      };
    },

    applyModelSet: async (companyId: string, name: string, _appliedBy?: string | null) => {
      const record = await getModelSetRecord(companyId, name);
      const [settingsRow, agentRows, departmentOverrideMap, profileOverrideMap] = await Promise.all([
        getInstanceSettingsRow(db),
        db.select().from(agents).where(eq(agents.companyId, companyId)).orderBy(asc(agents.name)),
        getDepartmentOverrideMap(companyId),
        getProfileOverrideMap(companyId),
      ]);

      let changedAgents = 0;
      for (const agentRow of agentRows) {
        const resolution = await resolveAgentModel(
          companyId,
          agentRow,
          record,
          departmentOverrideMap,
          profileOverrideMap,
        );
        if (resolution.source === "none") continue;
        const nextAdapterConfig = buildResolvedAdapterConfig(
          agentRow.adapterType,
          asRecord(agentRow.adapterConfig),
          resolution.provider,
          resolution.model,
        );
        const changed = JSON.stringify(nextAdapterConfig) !== JSON.stringify(asRecord(agentRow.adapterConfig));
        if (!changed) continue;
        changedAgents += 1;
        await db
          .update(agents)
          .set({
            adapterConfig: nextAdapterConfig,
            updatedAt: new Date(),
          })
          .where(eq(agents.id, agentRow.id));
      }

      const preferences = buildModelSetPreferences(settingsRow?.experimental ?? {});
      preferences.activeByCompany[companyId] = record.name;
      await upsertInstanceExperimentalSettings(
        db,
        buildExperimentalWithPreferences(settingsRow?.experimental ?? {}, preferences),
      );

      return {
        applied: true,
        companyId,
        name: record.name,
        source: record.source,
        changedAgents,
      };
    },

    listDepartmentOverrides: async (companyId: string) => {
      return db
        .select()
        .from(modelDepartmentOverrides)
        .where(eq(modelDepartmentOverrides.companyId, companyId))
        .orderBy(asc(modelDepartmentOverrides.department));
    },

    replaceDepartmentOverrides: async (companyId: string, overrides: ModelDepartmentOverrideInput[]) => {
      await db.delete(modelDepartmentOverrides).where(eq(modelDepartmentOverrides.companyId, companyId));
      if (overrides.length === 0) return [];
      const now = new Date();
      const inserted = await db
        .insert(modelDepartmentOverrides)
        .values(
          overrides.map((override) => ({
            companyId,
            department: override.department,
            provider: override.provider,
            model: override.model,
            reason: override.reason ?? null,
            createdAt: now,
            updatedAt: now,
          })),
        )
        .returning();
      return inserted.sort((a, b) => a.department.localeCompare(b.department));
    },

    listProfileOverrides: async (companyId: string) => {
      const rows = await db
        .select({
          id: modelProfileOverrides.id,
          companyId: modelProfileOverrides.companyId,
          agentId: modelProfileOverrides.agentId,
          agentName: agents.name,
          provider: modelProfileOverrides.provider,
          model: modelProfileOverrides.model,
          reason: modelProfileOverrides.reason,
          createdAt: modelProfileOverrides.createdAt,
          updatedAt: modelProfileOverrides.updatedAt,
        })
        .from(modelProfileOverrides)
        .innerJoin(agents, eq(modelProfileOverrides.agentId, agents.id))
        .where(eq(modelProfileOverrides.companyId, companyId))
        .orderBy(asc(agents.name));
      return rows;
    },

    upsertProfileOverride: async (
      companyId: string,
      agentId: string,
      input: { provider: string; model: string; reason?: string | null },
    ) => {
      const [agentRow] = await db
        .select({ id: agents.id, name: agents.name, companyId: agents.companyId })
        .from(agents)
        .where(and(eq(agents.companyId, companyId), eq(agents.id, agentId)))
        .limit(1);
      if (!agentRow) {
        throw notFound(`Agent "${agentId}" not found.`);
      }
      const now = new Date();
      const [row] = await db
        .insert(modelProfileOverrides)
        .values({
          companyId,
          agentId,
          provider: input.provider,
          model: input.model,
          reason: input.reason ?? null,
          createdAt: now,
          updatedAt: now,
        })
        .onConflictDoUpdate({
          target: [modelProfileOverrides.companyId, modelProfileOverrides.agentId],
          set: {
            provider: input.provider,
            model: input.model,
            reason: input.reason ?? null,
            updatedAt: now,
          },
        })
        .returning();
      return {
        ...row,
        agentName: agentRow.name,
      };
    },

    deleteProfileOverride: async (companyId: string, agentId: string) => {
      const existing = await db
        .select({ id: modelProfileOverrides.id })
        .from(modelProfileOverrides)
        .where(and(eq(modelProfileOverrides.companyId, companyId), eq(modelProfileOverrides.agentId, agentId)))
        .limit(1);
      if (existing.length === 0) {
        return { deleted: false, agentId };
      }
      await db
        .delete(modelProfileOverrides)
        .where(and(eq(modelProfileOverrides.companyId, companyId), eq(modelProfileOverrides.agentId, agentId)));
      return { deleted: true, agentId };
    },

    listPricing: async () => {
      return db.select().from(modelPricing).orderBy(asc(modelPricing.provider), asc(modelPricing.model));
    },

    upsertPricing: async (items: ModelPricingItem[]) => {
      const now = new Date();
      const results = [] as typeof modelPricing.$inferSelect[];
      for (const item of items) {
        const [row] = await db
          .insert(modelPricing)
          .values({
            provider: item.provider,
            model: item.model,
            inputCostPer1m: item.inputCostPer1m ?? null,
            outputCostPer1m: item.outputCostPer1m ?? null,
            pricingType: item.pricingType,
            monthlyEstimate: item.monthlyEstimate ?? null,
            updatedAt: now,
          })
          .onConflictDoUpdate({
            target: [modelPricing.provider, modelPricing.model],
            set: {
              inputCostPer1m: item.inputCostPer1m ?? null,
              outputCostPer1m: item.outputCostPer1m ?? null,
              pricingType: item.pricingType,
              monthlyEstimate: item.monthlyEstimate ?? null,
              updatedAt: now,
            },
          })
          .returning();
        results.push(row);
      }
      return results.sort(
        (a, b) => a.provider.localeCompare(b.provider) || a.model.localeCompare(b.model),
      );
    },

    costEstimate: async (companyId: string) => {
      const [agentRows, pricingRows, activeName, departmentOverrideMap, profileOverrideMap] =
        await Promise.all([
          db.select().from(agents).where(eq(agents.companyId, companyId)).orderBy(asc(agents.name)),
          db.select().from(modelPricing),
          getActiveModelSetName(companyId),
          getDepartmentOverrideMap(companyId),
          getProfileOverrideMap(companyId),
        ]);
      const activeSet = activeName ? await getModelSetRecord(companyId, activeName).catch(() => null) : null;
      const pricingByKey = new Map(
        pricingRows.map((row) => [`${row.provider}/${row.model}`, row] as const),
      );
      const items = [] as Array<{
        agentId: string;
        agentName: string;
        provider: string | null;
        model: string | null;
        source: ModelResolution["source"];
        setName: string | null;
        family: string | null;
        pricingType: string | null;
        monthlyEstimate: number | null;
        inputCostPer1m: number | null;
        outputCostPer1m: number | null;
      }>;
      let monthlyEstimateTotal = 0;
      for (const agentRow of agentRows) {
        const resolution = await resolveAgentModel(
          companyId,
          agentRow,
          activeSet,
          departmentOverrideMap,
          profileOverrideMap,
        );
        const pricing =
          resolution.provider && resolution.model
            ? pricingByKey.get(`${resolution.provider}/${resolution.model}`)
            : undefined;
        const monthlyEstimate = pricing?.monthlyEstimate ?? null;
        if (monthlyEstimate != null) {
          monthlyEstimateTotal += monthlyEstimate;
        }
        items.push({
          agentId: agentRow.id,
          agentName: agentRow.name,
          provider: resolution.provider || null,
          model: resolution.model || null,
          source: resolution.source,
          setName: resolution.setName,
          family: resolution.family,
          pricingType: pricing?.pricingType ?? null,
          monthlyEstimate,
          inputCostPer1m: pricing?.inputCostPer1m ?? null,
          outputCostPer1m: pricing?.outputCostPer1m ?? null,
        });
      }
      return {
        companyId,
        activeModelSetName: activeSet?.name ?? activeName,
        itemCount: items.length,
        monthlyEstimateTotal,
        items,
      };
    },
  };
}
