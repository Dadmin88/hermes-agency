import { describe, expect, it } from "vitest";
import {
  buildRoutingOverrideDraft,
  buildRoutingOverridePayload,
  changeRoutingOverrideProvider,
  validateRoutingOverrideDraft,
} from "./direct-model-routing-override";

describe("direct model routing override helpers", () => {
  it("builds an inherited draft from an approved effective route", () => {
    expect(buildRoutingOverrideDraft(null, {
      provider: "openai-codex",
      model: "gpt-5.6-terra",
      reasoningEffort: "medium",
    })).toEqual({
      provider: "openai-codex",
      model: "gpt-5.6-terra",
      reasoningEffort: "inherit",
      reason: "",
    });
  });

  it("does not copy an unavailable inherited route into a new override", () => {
    expect(buildRoutingOverrideDraft(null, {
      provider: "legacy-provider",
      model: "legacy-model",
      reasoningEffort: null,
    })).toMatchObject({ provider: "", model: "", reasoningEffort: "inherit" });
  });

  it("clears a model when provider changes and the model is incompatible", () => {
    expect(changeRoutingOverrideProvider({
      provider: "legacy-provider",
      model: "legacy-model",
      reasoningEffort: "high",
      reason: "keep this note",
    }, "openai-codex")).toEqual({
      provider: "openai-codex",
      model: "",
      reasoningEffort: "inherit",
      reason: "keep this note",
    });
  });

  it("omits inherited effort from the replacement PUT payload", () => {
    expect(buildRoutingOverridePayload({
      provider: " openai-codex ",
      model: " gpt-5.6-sol ",
      reasoningEffort: "inherit",
      reason: " ",
    })).toEqual({ provider: "openai-codex", model: "gpt-5.6-sol", reason: null });
  });

  it("rejects missing and unavailable provider/model values", () => {
    expect(validateRoutingOverrideDraft({
      provider: "openai-codex",
      model: "legacy-model",
      reasoningEffort: "inherit",
      reason: "",
    })).toEqual({ model: "This model is not available from openai-codex." });
  });
});
