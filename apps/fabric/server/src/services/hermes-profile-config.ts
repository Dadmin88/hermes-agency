import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import YAML from "yaml";

export type HermesProfileConfigWriteResult =
  | { status: "updated"; profile: string; configPath: string; provider: string; model: string }
  | { status: "unchanged"; profile: string; configPath: string }
  | { status: "skipped"; profile: string; reason: string }
  | { status: "error"; profile: string; error: string };

export function resolveHermesProfilesDir(): string {
  const override = process.env.HERMES_PROFILES_DIR?.trim();
  if (override) return path.resolve(override);
  return path.join(os.homedir(), ".hermes", "profiles");
}

export function resolveHermesProfileName(agent: { name: string; adapterConfig?: unknown }): string | null {
  const config = asRecord(agent.adapterConfig);
  const fromConfig = firstNonEmptyString([
    config.hermesProfile,
    config.profileName,
    config.profile,
  ]);
  if (fromConfig) return fromConfig;
  const trimmed = agent.name.trim();
  if (trimmed.startsWith("agency-")) return trimmed;
  return null;
}

export function profileConfigPath(profileName: string, profilesDir = resolveHermesProfilesDir()): string {
  return path.join(profilesDir, profileName, "config.yaml");
}

export async function readProfileConfigYaml(configPath: string): Promise<Record<string, unknown> | null> {
  try {
    const raw = await readFile(configPath, "utf8");
    const parsed = YAML.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function firstNonEmptyString(values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return null;
}

function currentModelBlock(data: Record<string, unknown>): { provider: string | null; model: string | null } {
  const model = data.model;
  if (!model || typeof model !== "object" || Array.isArray(model)) {
    return { provider: null, model: null };
  }
  const block = model as Record<string, unknown>;
  const provider = typeof block.provider === "string" ? block.provider : null;
  const defaultModel =
    typeof block.default === "string"
      ? block.default
      : typeof block.model === "string"
        ? block.model
        : null;
  return { provider, model: defaultModel };
}

function buildMinimalProfileConfig(provider: string, model: string, modelSetName: string, family: string | null) {
  const appliedAt = new Date().toISOString();
  return {
    model: {
      provider,
      default: model,
    },
    agency: {
      models: {
        active_set: modelSetName,
        applied_family: family,
        applied_at: appliedAt,
        managed_by: "hermes-fabric",
      },
    },
  };
}

function mergeModelIntoConfig(
  data: Record<string, unknown>,
  input: {
    provider: string;
    model: string;
    modelSetName: string;
    family: string | null;
  },
): Record<string, unknown> {
  const next = { ...data };
  next.model = { provider: input.provider, default: input.model };
  const agencyRaw = next.agency;
  const agency = asRecord(agencyRaw);
  const modelsRaw = agency.models;
  const models = asRecord(modelsRaw);
  models.active_set = input.modelSetName;
  models.applied_family = input.family;
  models.applied_at = new Date().toISOString();
  models.managed_by = "hermes-fabric";
  agency.models = models;
  next.agency = agency;
  return next;
}

async function atomicYamlWrite(configPath: string, data: Record<string, unknown>) {
  const dir = path.dirname(configPath);
  await mkdir(dir, { recursive: true });
  const tmpPath = path.join(dir, `.${path.basename(configPath)}.tmp`);
  const body = YAML.stringify(data, { sortMapEntries: false });
  await writeFile(tmpPath, body, "utf8");
  await rename(tmpPath, configPath);
}

export async function writeModelToProfileConfig(input: {
  profileName: string;
  provider: string;
  model: string;
  modelSetName: string;
  family?: string | null;
  profilesDir?: string;
}): Promise<HermesProfileConfigWriteResult> {
  const profilesDir = input.profilesDir ?? resolveHermesProfilesDir();
  const profile = input.profileName.trim();
  if (!profile) {
    return { status: "error", profile: input.profileName, error: "Profile name is empty." };
  }
  const configPath = profileConfigPath(profile, profilesDir);
  try {
    const existing = await readProfileConfigYaml(configPath);
    const family = input.family ?? null;
    if (existing === null) {
      const created = buildMinimalProfileConfig(input.provider, input.model, input.modelSetName, family);
      await atomicYamlWrite(configPath, created);
      return {
        status: "updated",
        profile,
        configPath,
        provider: input.provider,
        model: input.model,
      };
    }

    const current = currentModelBlock(existing);
    if (current.provider === input.provider && current.model === input.model) {
      return { status: "unchanged", profile, configPath };
    }

    const merged = mergeModelIntoConfig(existing, {
      provider: input.provider,
      model: input.model,
      modelSetName: input.modelSetName,
      family,
    });
    await atomicYamlWrite(configPath, merged);
    return {
      status: "updated",
      profile,
      configPath,
      provider: input.provider,
      model: input.model,
    };
  } catch (error) {
    return {
      status: "error",
      profile,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}