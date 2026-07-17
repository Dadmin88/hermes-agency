import type { ModelFamily, ModelSetDefinition } from "@hermes-fabric/shared";
import type { ModelSetPreviewChange } from "@/api/model-sets";

export const APPROVED_MODEL_SET_CATALOG = [
  {
    provider: "openai-codex",
    label: "OpenAI Codex",
    models: [
      { id: "gpt-5.6-sol", label: "Sol — coding and agent work" },
      { id: "gpt-5.6-terra", label: "Terra — general-purpose work" },
      { id: "gpt-5.6-luna", label: "Luna — text, reasoning, and tools" },
    ],
  },
] as const;

export const MODEL_SET_PROVIDER_OPTIONS = APPROVED_MODEL_SET_CATALOG.map((entry) => entry.provider);
export const REASONING_EFFORT_OPTIONS = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] as const;
export const CANONICAL_MODEL_SET_FAMILY_KEYS = [
  "coding_worker",
  "general_worker",
  "orchestration",
  "analysis_worker",
  "creative_worker",
  "luna_text_reasoning",
  "senior_review",
  "coding_light",
  "review_worker",
  "high_reasoning_review",
  "lightweight_worker",
] as const;

export interface ModelSetSelectOption {
  value: string;
  label: string;
  legacy?: boolean;
}

export interface LiveProfileOption {
  name: string;
  urlKey?: string | null;
}

function legacyOption(value: string, kind: string): ModelSetSelectOption[] {
  return value ? [{ value, label: `Legacy/unavailable ${kind}: ${value}`, legacy: true }] : [];
}

export function providerOptions(currentProvider = ""): ModelSetSelectOption[] {
  const approved = APPROVED_MODEL_SET_CATALOG.map(({ provider, label }) => ({ value: provider, label }));
  return approved.some((option) => option.value === currentProvider)
    ? approved
    : [...legacyOption(currentProvider, "provider"), ...approved];
}

export function modelOptions(provider: string, currentModel = ""): ModelSetSelectOption[] {
  const catalog = APPROVED_MODEL_SET_CATALOG.find((entry) => entry.provider === provider);
  const approved = catalog?.models.map(({ id, label }) => ({ value: id, label: `${label} (${id})` })) ?? [];
  return approved.some((option) => option.value === currentModel)
    ? approved
    : [...legacyOption(currentModel, "model"), ...approved];
}

export function firstApprovedModel(provider: string): string {
  return APPROVED_MODEL_SET_CATALOG.find((entry) => entry.provider === provider)?.models[0]?.id ?? "";
}

export function modelFamilyDefinition({
  provider,
  model,
  reasoningEffort,
  reason,
}: {
  provider: string;
  model: string;
  reasoningEffort?: string;
  reason?: string;
}) {
  return {
    provider: provider.trim(),
    model: model.trim(),
    reasoning_effort: (reasoningEffort || undefined) as ModelFamily["reasoning_effort"],
    reason: reason?.trim() || undefined,
  };
}

export function unusedCanonicalFamilyKeys(existingKeys: Iterable<string>): string[] {
  const existing = new Set(existingKeys);
  return CANONICAL_MODEL_SET_FAMILY_KEYS.filter((key) => !existing.has(key));
}

export function liveAgencyProfileOptions(
  profiles: readonly LiveProfileOption[],
  selectedProfiles: Iterable<string>,
  currentProfile = "",
): ModelSetSelectOption[] {
  const selected = new Set(selectedProfiles);
  const available = new Map<string, ModelSetSelectOption>();
  for (const profile of profiles) {
    const name = profile.name?.startsWith("agency-")
      ? profile.name
      : profile.urlKey?.startsWith("agency-")
        ? profile.urlKey
        : null;
    if (!name || (selected.has(name) && name !== currentProfile)) continue;
    available.set(name, {
      value: name,
      label: profile.urlKey && profile.urlKey !== name ? `${name} (${profile.urlKey})` : name,
    });
  }
  const options = Array.from(available.values()).sort((a, b) => a.label.localeCompare(b.label));
  return options.some((option) => option.value === currentProfile)
    ? options
    : [...legacyOption(currentProfile, "profile"), ...options];
}

const PREMIUM_HINTS = ["gpt-5", "claude-opus", "claude-sonnet-4", "o3", "grok-4"];

export function emptyModelSetDefinition(name = "custom-set"): ModelSetDefinition {
  return {
    version: 1,
    name,
    description: "Custom model routing preset",
    defaults: { family: "general_worker" },
    families: {
      general_worker: {
        provider: "openai-codex",
        model: "gpt-5.6-sol",
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
