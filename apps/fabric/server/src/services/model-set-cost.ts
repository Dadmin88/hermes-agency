import { and, eq, gte, sql } from "drizzle-orm";
import { agents, costEvents, modelPricing, type Db } from "@hermes-fabric/db";
import type { ModelCostEstimateItem, ModelCostEstimateMethod } from "@hermes-fabric/shared";

type PricingRow = typeof modelPricing.$inferSelect;
type AgentRow = typeof agents.$inferSelect;

export type ModelResolutionLike = {
  provider: string;
  model: string;
  source: string;
  setName: string | null;
  family: string | null;
};

export function formatMonthlyEstimateLabel(value: number | null): string {
  if (value == null) return "N/A";
  return `$${value.toFixed(2)}`;
}

export function resolveAgentMonthlyEstimate(
  pricing: PricingRow | undefined,
  historicalDollars: number | null,
): {
  monthlyEstimate: number | null;
  estimateMethod: ModelCostEstimateMethod;
  monthlyEstimateLabel: string;
} {
  if (!pricing) {
    return { monthlyEstimate: null, estimateMethod: "unknown", monthlyEstimateLabel: "N/A" };
  }
  if (pricing.pricingType === "local") {
    return { monthlyEstimate: 0, estimateMethod: "local_zero", monthlyEstimateLabel: "$0.00" };
  }
  if (pricing.pricingType === "subscription" || pricing.pricingType === "manual") {
    if (pricing.monthlyEstimate != null) {
      return {
        monthlyEstimate: pricing.monthlyEstimate,
        estimateMethod: "monthly_estimate",
        monthlyEstimateLabel: formatMonthlyEstimateLabel(pricing.monthlyEstimate),
      };
    }
    return { monthlyEstimate: null, estimateMethod: "unknown", monthlyEstimateLabel: "N/A" };
  }
  if (pricing.pricingType === "api") {
    if (pricing.monthlyEstimate != null) {
      return {
        monthlyEstimate: pricing.monthlyEstimate,
        estimateMethod: "monthly_estimate",
        monthlyEstimateLabel: formatMonthlyEstimateLabel(pricing.monthlyEstimate),
      };
    }
    if (historicalDollars != null) {
      return {
        monthlyEstimate: historicalDollars,
        estimateMethod: "historical",
        monthlyEstimateLabel: formatMonthlyEstimateLabel(historicalDollars),
      };
    }
    return { monthlyEstimate: null, estimateMethod: "unknown", monthlyEstimateLabel: "N/A" };
  }
  if (pricing.monthlyEstimate != null) {
    return {
      monthlyEstimate: pricing.monthlyEstimate,
      estimateMethod: "monthly_estimate",
      monthlyEstimateLabel: formatMonthlyEstimateLabel(pricing.monthlyEstimate),
    };
  }
  return { monthlyEstimate: null, estimateMethod: "unknown", monthlyEstimateLabel: "N/A" };
}

export async function loadHistoricalSpendByAgentModel(db: Db, companyId: string) {
  const since = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
  const rows = await db
    .select({
      agentId: costEvents.agentId,
      provider: costEvents.provider,
      model: costEvents.model,
      totalCents: sql<number>`coalesce(sum(${costEvents.costCents}), 0)`.mapWith(Number),
    })
    .from(costEvents)
    .where(and(eq(costEvents.companyId, companyId), gte(costEvents.occurredAt, since)))
    .groupBy(costEvents.agentId, costEvents.provider, costEvents.model);
  return new Map(
    rows.map((row) => [`${row.agentId}|${row.provider}|${row.model}`, row.totalCents / 100] as const),
  );
}

export function buildCostEstimateItems(input: {
  agentRows: AgentRow[];
  pricingByKey: Map<string, PricingRow>;
  historicalByKey: Map<string, number>;
  resolve: (agent: AgentRow) => ModelResolutionLike;
}): {
  items: ModelCostEstimateItem[];
  monthlyEstimateTotal: number;
  unknownPricingCount: number;
  actualSpendLast30DaysTotal: number;
} {
  const items: ModelCostEstimateItem[] = [];
  let monthlyEstimateTotal = 0;
  let unknownPricingCount = 0;
  let actualSpendLast30DaysTotal = 0;

  for (const agentRow of input.agentRows) {
    const resolution = input.resolve(agentRow);
    const pricing =
      resolution.provider && resolution.model
        ? input.pricingByKey.get(`${resolution.provider}/${resolution.model}`)
        : undefined;
    const historicalKey =
      resolution.provider && resolution.model
        ? `${agentRow.id}|${resolution.provider}|${resolution.model}`
        : null;
    const historicalDollars = historicalKey ? (input.historicalByKey.get(historicalKey) ?? null) : null;
    if (historicalDollars != null) {
      actualSpendLast30DaysTotal += historicalDollars;
    }
    const estimate = resolveAgentMonthlyEstimate(pricing, historicalDollars);
    if (estimate.estimateMethod === "unknown") {
      unknownPricingCount += 1;
    } else if (estimate.monthlyEstimate != null) {
      monthlyEstimateTotal += estimate.monthlyEstimate;
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
      monthlyEstimate: estimate.monthlyEstimate,
      monthlyEstimateLabel: estimate.monthlyEstimateLabel,
      inputCostPer1m: pricing?.inputCostPer1m ?? null,
      outputCostPer1m: pricing?.outputCostPer1m ?? null,
      actualSpendLast30Days: historicalDollars,
      estimateMethod: estimate.estimateMethod,
    });
  }

  return {
    items,
    monthlyEstimateTotal,
    unknownPricingCount,
    actualSpendLast30DaysTotal,
  };
}

type OpenRouterModel = {
  id: string;
  pricing?: {
    prompt?: string;
    completion?: string;
  };
};

export async function discoverOpenRouterPricing(): Promise<
  Array<{
    provider: string;
    model: string;
    pricingType: "api";
    inputCostPer1m: number | null;
    outputCostPer1m: number | null;
    monthlyEstimate: null;
  }>
> {
  const response = await fetch("https://openrouter.ai/api/v1/models", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`OpenRouter pricing fetch failed with status ${response.status}`);
  }
  const payload = (await response.json()) as { data?: OpenRouterModel[] };
  const models = Array.isArray(payload.data) ? payload.data : [];
  return models.map((model) => {
    const prompt = model.pricing?.prompt != null ? Number(model.pricing.prompt) : NaN;
    const completion = model.pricing?.completion != null ? Number(model.pricing.completion) : NaN;
    return {
      provider: "openrouter",
      model: model.id,
      pricingType: "api" as const,
      inputCostPer1m: Number.isFinite(prompt) ? prompt * 1_000_000 : null,
      outputCostPer1m: Number.isFinite(completion) ? completion * 1_000_000 : null,
      monthlyEstimate: null,
    };
  });
}