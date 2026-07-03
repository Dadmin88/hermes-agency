import { describe, expect, it } from "vitest";
import { changeDirection, validateModelSetDefinition } from "./model-set-ui";

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