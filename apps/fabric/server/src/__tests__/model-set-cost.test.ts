import { describe, expect, it } from "vitest";
import {
  formatMonthlyEstimateLabel,
  resolveAgentMonthlyEstimate,
} from "../services/model-set-cost.js";

describe("model-set-cost helpers", () => {
  it("formats monthly estimate labels", () => {
    expect(formatMonthlyEstimateLabel(null)).toBe("N/A");
    expect(formatMonthlyEstimateLabel(12.5)).toBe("$12.50");
  });

  it("treats local pricing as zero", () => {
    const result = resolveAgentMonthlyEstimate(
      {
        id: "1",
        provider: "local",
        model: "llama",
        inputCostPer1m: null,
        outputCostPer1m: null,
        pricingType: "local",
        monthlyEstimate: null,
        updatedAt: new Date(),
      },
      null,
    );
    expect(result.monthlyEstimate).toBe(0);
    expect(result.estimateMethod).toBe("local_zero");
  });

  it("requires monthly estimate for subscription pricing", () => {
    const missing = resolveAgentMonthlyEstimate(
      {
        id: "1",
        provider: "openai",
        model: "gpt-4",
        inputCostPer1m: null,
        outputCostPer1m: null,
        pricingType: "subscription",
        monthlyEstimate: null,
        updatedAt: new Date(),
      },
      null,
    );
    expect(missing.monthlyEstimateLabel).toBe("N/A");

    const present = resolveAgentMonthlyEstimate(
      {
        id: "1",
        provider: "openai",
        model: "gpt-4",
        inputCostPer1m: null,
        outputCostPer1m: null,
        pricingType: "subscription",
        monthlyEstimate: 20,
        updatedAt: new Date(),
      },
      null,
    );
    expect(present.monthlyEstimate).toBe(20);
    expect(present.estimateMethod).toBe("monthly_estimate");
  });

  it("falls back to historical spend for api pricing", () => {
    const result = resolveAgentMonthlyEstimate(
      {
        id: "1",
        provider: "openrouter",
        model: "anthropic/claude-sonnet-4",
        inputCostPer1m: 3,
        outputCostPer1m: 15,
        pricingType: "api",
        monthlyEstimate: null,
        updatedAt: new Date(),
      },
      42.25,
    );
    expect(result.monthlyEstimate).toBe(42.25);
    expect(result.estimateMethod).toBe("historical");
  });
});