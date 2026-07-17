import { describe, expect, it } from "vitest";
import {
  changeDirection,
  liveAgencyProfileOptions,
  modelFamilyDefinition,
  modelOptions,
  providerOptions,
  unusedCanonicalFamilyKeys,
  validateModelSetDefinition,
} from "./model-set-ui";

describe("model-set-ui", () => {
  it("flags missing families in validation", () => {
    const errors = validateModelSetDefinition({
      version: 1,
      name: "broken",
      defaults: { family: "missing" },
      families: {},
      profiles: {},
    });
    expect(errors.some((message) => message.includes("At least one model family"))).toBe(true);
    expect(errors.some((message) => message.includes("Default family"))).toBe(true);
  });

  it("limits the approved catalog to openai-codex and 5.6 models while preserving legacy values", () => {
    expect(providerOptions().map((option) => option.value)).toEqual(["openai-codex"]);
    expect(modelOptions("openai-codex").map((option) => option.value)).toEqual([
      "gpt-5.6-sol",
      "gpt-5.6-terra",
      "gpt-5.6-luna",
    ]);
    expect(providerOptions("openai")[0]).toMatchObject({
      value: "openai",
      legacy: true,
      label: "Legacy/unavailable provider: openai",
    });
    expect(modelOptions("openai-codex", "gpt-5.5")[0]).toMatchObject({
      value: "gpt-5.5",
      legacy: true,
    });
  });

  it("omits inherited reasoning effort and round-trips an explicit effort", () => {
    expect(modelFamilyDefinition({ provider: "openai-codex", model: "gpt-5.6-sol", reasoningEffort: "" }))
      .toMatchObject({ provider: "openai-codex", model: "gpt-5.6-sol", reasoning_effort: undefined });
    expect(modelFamilyDefinition({ provider: "openai-codex", model: "gpt-5.6-terra", reasoningEffort: "high" }))
      .toMatchObject({ reasoning_effort: "high" });
  });

  it("excludes mapped Agency profiles while retaining a missing legacy mapping", () => {
    const options = liveAgencyProfileOptions(
      [
        { name: "agency-orchestrator", urlKey: "agency-orchestrator" },
        { name: "Agency reviewer", urlKey: "agency-reviewer" },
        { name: "Non Agency", urlKey: "non-agency" },
      ],
      ["agency-orchestrator"],
      "agency-missing",
    );
    expect(options.map((option) => option.value)).toEqual(["agency-missing", "agency-reviewer"]);
    expect(options[0]).toMatchObject({ legacy: true, label: "Legacy/unavailable profile: agency-missing" });
  });

  it("only offers unused canonical family identifiers for selector-based addition", () => {
    const options = unusedCanonicalFamilyKeys(["general_worker", "legacy_worker"]);
    expect(options).not.toContain("general_worker");
    expect(options).toContain("coding_worker");
    expect(options).not.toContain("legacy_worker");
  });

  it("classifies preview direction", () => {
    const direction = changeDirection({
      agentId: "a1",
      agentName: "Agent",
      adapterType: "hermes_local",
      before: { provider: "openai", model: "gpt-4o-mini" },
      after: { provider: "openai-codex", model: "gpt-5.5" },
      family: "review_worker",
      source: "profile",
    });
    expect(direction).toBe("up");
  });
});
