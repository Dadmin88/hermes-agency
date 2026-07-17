import type { ModelPricingItem, ModelSetDefinition, ReasoningEffort } from "../validators/model-set.js";

export type ModelSetListItem = {
  id: string;
  companyId: string | null;
  name: string;
  description: string | null;
  source: "custom" | "packaged";
  active: boolean;
  familyCount: number;
  profileCount: number;
  createdBy: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  monthlyEstimateTotal: number | null;
  monthlyEstimateLabel: string;
  unknownPricingCount: number;
};

export type ModelSetDetail = {
  id: string;
  companyId: string | null;
  name: string;
  description: string | null;
  source: "custom" | "packaged";
  active: boolean;
  definition: ModelSetDefinition;
  createdBy: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  monthlyEstimateTotal: number | null;
  monthlyEstimateLabel: string;
  unknownPricingCount: number;
  agentCostBreakdown: ModelCostEstimateItem[];
};

export type ModelCostEstimateMethod =
  | "monthly_estimate"
  | "historical"
  | "local_zero"
  | "unknown";

export type ModelResolvedRouting = {
  provider: string | null;
  model: string | null;
  reasoningEffort: ReasoningEffort | null;
  source: string;
  setName: string | null;
  family: string | null;
  reason: string | null;
};

export type ModelCostEstimateItem = {
  agentId: string;
  agentName: string;
  provider: string | null;
  model: string | null;
  reasoningEffort: ReasoningEffort | null;
  source: string;
  setName: string | null;
  family: string | null;
  reason: string | null;
  inheritedRouting: ModelResolvedRouting;
  pricingType: string | null;
  monthlyEstimate: number | null;
  monthlyEstimateLabel: string;
  inputCostPer1m: number | null;
  outputCostPer1m: number | null;
  actualSpendLast30Days: number | null;
  estimateMethod: ModelCostEstimateMethod;
};

export type ModelCostEstimateResponse = {
  companyId: string;
  activeModelSetName: string | null;
  itemCount: number;
  monthlyEstimateTotal: number;
  monthlyEstimateLabel: string;
  unknownPricingCount: number;
  actualSpendLast30DaysTotal: number | null;
  items: ModelCostEstimateItem[];
};

export type ModelPricingRow = ModelPricingItem & {
  id?: string;
  updatedAt?: string;
};

export type ModelPricingAutoDetectResult = {
  provider: string;
  discovered: number;
  upserted: number;
  items: ModelPricingRow[];
};