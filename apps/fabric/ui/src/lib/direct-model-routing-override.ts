import type { ReasoningEffort } from "@hermes-fabric/shared";
import {
  APPROVED_MODEL_SET_CATALOG,
  REASONING_EFFORT_OPTIONS,
} from "./model-set-ui";

export type RoutingOverrideEffort = ReasoningEffort | "inherit";

export interface RoutingOverrideDraft {
  provider: string;
  model: string;
  reasoningEffort: RoutingOverrideEffort;
  reason: string;
}

export interface RoutingOverrideValue {
  provider: string;
  model: string;
  reasoningEffort: ReasoningEffort | null;
  reason?: string | null;
}

export interface EffectiveRoutingValue {
  provider: string | null;
  model: string | null;
  reasoningEffort: ReasoningEffort | null;
}

export type RoutingOverrideErrors = Partial<Record<"provider" | "model" | "reasoningEffort" | "reason", string>>;

export function isApprovedRoutingProvider(provider: string): boolean {
  return APPROVED_MODEL_SET_CATALOG.some((entry) => entry.provider === provider);
}

export function isApprovedRoutingModel(provider: string, model: string): boolean {
  return APPROVED_MODEL_SET_CATALOG.some(
    (entry) => entry.provider === provider && entry.models.some((candidate) => candidate.id === model),
  );
}

export function buildRoutingOverrideDraft(
  directOverride: RoutingOverrideValue | null,
  effectiveRouting: EffectiveRoutingValue | null,
): RoutingOverrideDraft {
  if (directOverride) {
    return {
      provider: directOverride.provider,
      model: directOverride.model,
      reasoningEffort: directOverride.reasoningEffort ?? "inherit",
      reason: directOverride.reason ?? "",
    };
  }

  const provider = effectiveRouting?.provider ?? "";
  const model = effectiveRouting?.model ?? "";
  const canCopy = isApprovedRoutingModel(provider, model);
  return {
    provider: canCopy ? provider : "",
    model: canCopy ? model : "",
    reasoningEffort: "inherit",
    reason: "",
  };
}

export function changeRoutingOverrideProvider(
  draft: RoutingOverrideDraft,
  provider: string,
): RoutingOverrideDraft {
  const model = isApprovedRoutingModel(provider, draft.model) ? draft.model : "";
  return {
    ...draft,
    provider,
    model,
    reasoningEffort: model ? draft.reasoningEffort : "inherit",
  };
}

export function validateRoutingOverrideDraft(draft: RoutingOverrideDraft): RoutingOverrideErrors {
  const errors: RoutingOverrideErrors = {};
  const provider = draft.provider.trim();
  const model = draft.model.trim();
  if (!provider) errors.provider = "Choose a provider.";
  else if (!isApprovedRoutingProvider(provider)) errors.provider = "Choose an available provider.";
  if (!model) errors.model = "Choose a model.";
  else if (provider && !isApprovedRoutingModel(provider, model)) {
    errors.model = `This model is not available from ${provider}.`;
  }
  if (
    draft.reasoningEffort !== "inherit" &&
    !REASONING_EFFORT_OPTIONS.includes(draft.reasoningEffort)
  ) {
    errors.reasoningEffort = `${draft.reasoningEffort} is not supported by ${model || "this model"}.`;
  }
  if (draft.reason.trim().length > 500) errors.reason = "Reason must be 500 characters or fewer.";
  return errors;
}

export function buildRoutingOverridePayload(draft: RoutingOverrideDraft): {
  provider: string;
  model: string;
  reasoningEffort?: ReasoningEffort;
  reason: string | null;
} {
  const payload: {
    provider: string;
    model: string;
    reasoningEffort?: ReasoningEffort;
    reason: string | null;
  } = {
    provider: draft.provider.trim(),
    model: draft.model.trim(),
    reason: draft.reason.trim() || null,
  };
  if (draft.reasoningEffort !== "inherit") payload.reasoningEffort = draft.reasoningEffort;
  return payload;
}
