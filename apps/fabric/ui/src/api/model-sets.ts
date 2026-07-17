import type {
  ModelSetDefinition,
  ModelSetDefinitionPatch,
  ModelPricingItem,
  ReasoningEffort,
} from "@hermes-fabric/shared";
import { api } from "./client";

export type ModelSetSource = "packaged" | "custom";

export interface ModelSetSummary {
  id: string;
  companyId: string | null;
  name: string;
  description: string | null;
  source: ModelSetSource;
  active: boolean;
  familyCount: number;
  profileCount: number;
  createdBy: string | null;
  createdAt: string;
  updatedAt: string;
  monthlyEstimateTotal?: number | null;
  monthlyEstimateLabel?: string;
  unknownPricingCount?: number;
}

export interface ModelSetDetail extends ModelSetSummary {
  definition: ModelSetDefinition;
  agentCostBreakdown?: ModelCostEstimateItem[];
}

export interface ModelCostEstimateItem {
  agentId: string;
  agentName: string;
  provider: string | null;
  model: string | null;
  reasoningEffort: ReasoningEffort | null;
  source: string;
  setName: string | null;
  family: string | null;
  reason: string | null;
  inheritedRouting: {
    provider: string | null;
    model: string | null;
    reasoningEffort: ReasoningEffort | null;
    source: string;
    setName: string | null;
    family: string | null;
    reason: string | null;
  };
  pricingType: string | null;
  monthlyEstimate: number | null;
  monthlyEstimateLabel?: string;
  inputCostPer1m: number | null;
  outputCostPer1m: number | null;
  actualSpendLast30Days?: number | null;
  estimateMethod?: string;
}

export interface ModelSetPreviewChange {
  agentId: string;
  agentName: string;
  adapterType: string;
  before: { provider: string | null; model: string | null };
  after: { provider: string; model: string };
  family: string | null;
  source: string;
}

export interface ModelSetPreview {
  companyId: string;
  name: string;
  source: ModelSetSource;
  changes: ModelSetPreviewChange[];
}

export interface ProfileConfigApplySummary {
  updated: Array<{ profile: string; provider: string; model: string }>;
  unchanged: string[];
  skipped: Array<{ profile: string; reason: string }>;
  errors: Array<{ profile: string; error: string }>;
}

export interface GatewayRestartSummary {
  attempted: Array<{ agentId: string; agentName: string; profile: string }>;
  skipped: Array<{ agentId: string; agentName: string; reason: string; detail?: string }>;
  errors: Array<{ agentId: string; agentName: string; error: string }>;
}

export interface ModelSetApplyResult {
  applied: boolean;
  companyId: string;
  name: string;
  source: ModelSetSource;
  changedAgents: number;
  profileConfigs?: ProfileConfigApplySummary;
  agentChanges?: Array<{
    agentId: string;
    agentName: string;
    adapterType: string;
    provider: string;
    model: string;
    source: string;
    profile: string | null;
  }>;
  gatewayRestart?: GatewayRestartSummary;
}

export interface DepartmentOverride {
  id?: string;
  companyId?: string;
  department: string;
  provider: string;
  model: string;
  reason: string | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface ProfileOverride {
  id: string;
  companyId: string;
  agentId: string;
  agentName: string;
  provider: string;
  model: string;
  reasoningEffort: ReasoningEffort | null;
  reason: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ModelPricingRow {
  id?: string;
  provider: string;
  model: string;
  inputCostPer1m: number | null;
  outputCostPer1m: number | null;
  pricingType: ModelPricingItem["pricingType"];
  monthlyEstimate: number | null;
  updatedAt?: string;
}

export interface ModelCostEstimate {
  companyId: string;
  activeModelSetName: string | null;
  itemCount: number;
  monthlyEstimateTotal: number;
  monthlyEstimateLabel?: string;
  unknownPricingCount?: number;
  actualSpendLast30DaysTotal?: number | null;
  items: ModelCostEstimateItem[];
}

export interface ModelPricingAutoDetectResult {
  provider: string;
  discovered: number;
  upserted: number;
  items: ModelPricingRow[];
}

function companyQuery(companyId: string): string {
  return `?companyId=${encodeURIComponent(companyId)}`;
}

export const modelSetsApi = {
  listSets: (companyId: string) =>
    api.get<ModelSetSummary[]>(`/model-sets${companyQuery(companyId)}`),

  getSet: (companyId: string, name: string) =>
    api.get<ModelSetDetail>(`/model-sets/${encodeURIComponent(name)}${companyQuery(companyId)}`),

  createSet: (
    companyId: string,
    input: { definition: ModelSetDefinition; description?: string | null },
  ) =>
    api.post<ModelSetDetail>("/model-sets", {
      companyId,
      definition: input.definition,
      description: input.description ?? null,
    }),

  updateSet: (
    companyId: string,
    name: string,
    input: { definition?: ModelSetDefinitionPatch; description?: string | null },
  ) =>
    api.put<ModelSetDetail>(`/model-sets/${encodeURIComponent(name)}`, {
      companyId,
      definition: input.definition,
      description: input.description,
    }),

  deleteSet: (companyId: string, name: string) =>
    api.delete<{ deleted: boolean; name: string }>(
      `/model-sets/${encodeURIComponent(name)}${companyQuery(companyId)}`,
    ),

  previewApply: (companyId: string, name: string) =>
    api.get<ModelSetPreview>(
      `/model-sets/${encodeURIComponent(name)}/preview${companyQuery(companyId)}`,
    ),

  applySet: (
    companyId: string,
    name: string,
    options?: { restartIdleGateways?: boolean },
  ) =>
    api.post<ModelSetApplyResult>(`/model-sets/${encodeURIComponent(name)}/apply`, {
      companyId,
      restartIdleGateways: options?.restartIdleGateways ?? false,
    }),

  listDepartmentOverrides: (companyId: string) =>
    api.get<DepartmentOverride[]>(`/model-overrides/department${companyQuery(companyId)}`),

  updateDepartmentOverrides: (companyId: string, overrides: DepartmentOverride[]) =>
    api.put<DepartmentOverride[]>("/model-overrides/department", {
      companyId,
      overrides: overrides.map(({ department, provider, model, reason }) => ({
        department,
        provider,
        model,
        reason,
      })),
    }),

  listProfileOverrides: (companyId: string) =>
    api.get<ProfileOverride[]>(`/model-overrides/profile${companyQuery(companyId)}`),

  updateProfileOverride: (
    companyId: string,
    agentId: string,
    input: { provider: string; model: string; reasoningEffort?: ReasoningEffort; reason?: string | null },
  ) =>
    api.put<ProfileOverride>(`/model-overrides/profile/${encodeURIComponent(agentId)}`, {
      companyId,
      provider: input.provider,
      model: input.model,
      ...(input.reasoningEffort === undefined ? {} : { reasoningEffort: input.reasoningEffort }),
      reason: input.reason ?? null,
    }),

  deleteProfileOverride: (companyId: string, agentId: string) =>
    api.delete<{ deleted: boolean; agentId: string }>(
      `/model-overrides/profile/${encodeURIComponent(agentId)}${companyQuery(companyId)}`,
    ),

  listPricing: () => api.get<ModelPricingRow[]>("/model-pricing"),

  updatePricing: (items: ModelPricingItem[]) =>
    api.put<ModelPricingRow[]>("/model-pricing", { items }),

  autoDetectOpenRouterPricing: () =>
    api.post<ModelPricingAutoDetectResult>("/model-pricing/auto-detect", {}),

  getCostEstimate: (companyId: string) =>
    api.get<ModelCostEstimate>(`/model-cost-estimate${companyQuery(companyId)}`),
};