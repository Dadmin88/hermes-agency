import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type {
  AdapterSkillContext,
  AdapterSkillSnapshot,
} from "@hermes-fabric/adapter-utils";
import {
  buildRuntimeMountedSkillSnapshot,
  readHermesFabricRuntimeSkillEntries,
  readInstalledSkillTargets,
  resolveHermesFabricDesiredSkillNames,
} from "@hermes-fabric/adapter-utils/server-utils";

const __moduleDir = path.dirname(fileURLToPath(import.meta.url));

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function resolveClaudeSkillsHome(config: Record<string, unknown>) {
  const env =
    typeof config.env === "object" && config.env !== null && !Array.isArray(config.env)
      ? (config.env as Record<string, unknown>)
      : {};
  const configuredHome = asString(env.HOME);
  const home = configuredHome ? path.resolve(configuredHome) : os.homedir();
  return path.join(home, ".claude", "skills");
}

async function buildClaudeSkillSnapshot(config: Record<string, unknown>): Promise<AdapterSkillSnapshot> {
  const availableEntries = await readHermesFabricRuntimeSkillEntries(config, __moduleDir);
  const desiredSkills = resolveHermesFabricDesiredSkillNames(config, availableEntries);
  const skillsHome = resolveClaudeSkillsHome(config);
  const installed = await readInstalledSkillTargets(skillsHome);
  return buildRuntimeMountedSkillSnapshot({
    adapterType: "claude_local",
    availableEntries,
    desiredSkills,
    configuredDetail: "Will be materialized into the stable HermesFabric-managed Claude prompt bundle on the next run.",
    externalInstalled: installed,
    externalLocationLabel: "~/.claude/skills",
    externalDetail: "Installed outside HermesFabric management in the Claude skills home.",
    skillsHome,
  });
}

export async function listClaudeSkills(ctx: AdapterSkillContext): Promise<AdapterSkillSnapshot> {
  return buildClaudeSkillSnapshot(ctx.config);
}

export async function syncClaudeSkills(
  ctx: AdapterSkillContext,
  _desiredSkills: string[],
): Promise<AdapterSkillSnapshot> {
  return buildClaudeSkillSnapshot(ctx.config);
}

export function resolveClaudeDesiredSkillNames(
  config: Record<string, unknown>,
  availableEntries: Array<{ key: string; required?: boolean }>,
) {
  return resolveHermesFabricDesiredSkillNames(config, availableEntries);
}
