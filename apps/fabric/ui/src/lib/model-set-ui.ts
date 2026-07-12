import type { ModelSetDefinition } from "@hermes-fabric/shared";
import type { ModelSetPreviewChange } from "@/api/model-sets";

export const MODEL_SET_PROVIDER_OPTIONS = [
  "openai-codex",
  "openai",
  "xai-oauth",
  "xai",
  "opencode-go",
  "anthropic",
  "openrouter",
  "groq",
  "google",
  "local",
] as const;

const PREMIUM_HINTS = ["gpt-5", "claude-opus", "claude-sonnet-4", "o3", "grok-4"];

export function emptyModelSetDefinition(name = "custom-set"): ModelSetDefinition {
  return {
    version: 1,
    name,
    description: "Custom model routing preset",
    defaults: { family: "general_worker" },
    families: {
      general_worker: {
        provider: "opencode-go",
        model: "",
        reason: "Default worker tier",
      },
    },
    profiles: {},
    escalation: {
      default_family: "general_worker",
      triggers: [],
    },
    budget: {
      max_input_cost_per_1m: null,
      max_output_cost_per_1m: null,
      warn_if_unknown_pricing: true,
    },
  };
}

export function validateModelSetDefinition(definition: ModelSetDefinition): string[] {
  const errors: string[] = [];
  if (!definition.name.trim()) errors.push("Set name is required.");
  if (!definition.defaults?.family?.trim()) errors.push("Default family is required.");
  const families = definition.families ?? {};
  if (Object.keys(families).length === 0) errors.push("At least one model family is required.");
  if (definition.defaults?.family && !families[definition.defaults.family]) {
    errors.push(`Default family "${definition.defaults.family}" is not defined.`);
  }
  for (const [familyName, family] of Object.entries(families)) {
    if (!family.provider?.trim()) errors.push(`Family "${familyName}" needs a provider.`);
    if (!family.model?.trim()) errors.push(`Family "${familyName}" needs a model.`);
  }
  for (const [profile, familyName] of Object.entries(definition.profiles ?? {})) {
    if (!families[familyName]) {
      errors.push(`Profile "${profile}" maps to unknown family "${familyName}".`);
    }
  }
  const escalationFamily = definition.escalation?.default_family;
  if (escalationFamily && !families[escalationFamily]) {
    errors.push(`Escalation family "${escalationFamily}" is not defined.`);
  }
  return errors;
}

function modelTierScore(provider: string | null, model: string | null): number {
  const haystack = `${provider ?? ""}/${model ?? ""}`.toLowerCase();
  let score = haystack.length;
  for (const hint of PREMIUM_HINTS) {
    if (haystack.includes(hint)) score += 40;
  }
  return score;
}

export function changeDirection(change: ModelSetPreviewChange): "up" | "down" | "same" {
  const beforeScore = modelTierScore(change.before.provider, change.before.model);
  const afterScore = modelTierScore(change.after.provider, change.after.model);
  if (beforeScore === afterScore && change.before.provider === change.after.provider && change.before.model === change.after.model) {
    return "same";
  }
  return afterScore >= beforeScore ? "up" : "down";
}

export function formatModelRef(provider: string | null, model: string | null): string {
  if (!provider && !model) return "—";
  if (!provider) return model ?? "—";
  if (!model) return provider;
  return `${provider} / ${model}`;
}