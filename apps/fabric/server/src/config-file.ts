import fs from "node:fs";
import { fabricConfigSchema, type HermesFabricConfig } from "@hermes-fabric/shared";
import { resolveHermesFabricConfigPath } from "./paths.js";

export function readConfigFile(): HermesFabricConfig | null {
  const configPath = resolveHermesFabricConfigPath();

  if (!fs.existsSync(configPath)) return null;

  try {
    const raw = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    return fabricConfigSchema.parse(raw);
  } catch {
    return null;
  }
}
