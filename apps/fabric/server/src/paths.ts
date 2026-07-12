import fs from "node:fs";
import path from "node:path";
import { resolveDefaultConfigPath } from "./home-paths.js";
import { fabricEnv } from "./fabric-env.js";

const HERMES_FABRIC_CONFIG_BASENAME = "config.json";
const HERMES_FABRIC_ENV_FILENAME = ".env";

function findConfigFileFromAncestors(startDir: string): string | null {
  const absoluteStartDir = path.resolve(startDir);
  let currentDir = absoluteStartDir;

  while (true) {
    const candidate = path.resolve(currentDir, ".fabric", HERMES_FABRIC_CONFIG_BASENAME);
    if (fs.existsSync(candidate)) {
      return candidate;
    }

    const nextDir = path.resolve(currentDir, "..");
    if (nextDir === currentDir) break;
    currentDir = nextDir;
  }

  return null;
}

export function resolveHermesFabricConfigPath(overridePath?: string): string {
  if (overridePath) return path.resolve(overridePath);
  const configFromEnv = fabricEnv("CONFIG");
  if (configFromEnv) return path.resolve(configFromEnv);
  return findConfigFileFromAncestors(process.cwd()) ?? resolveDefaultConfigPath();
}

export function resolveHermesFabricEnvPath(overrideConfigPath?: string): string {
  return path.resolve(path.dirname(resolveHermesFabricConfigPath(overrideConfigPath)), HERMES_FABRIC_ENV_FILENAME);
}
