import os from "node:os";
import path from "node:path";

export const DEFAULT_HERMES_FABRIC_INSTANCE_ID = "default";
export const HERMES_FABRIC_CONFIG_BASENAME = "config.json";
export const HERMES_FABRIC_ENV_FILENAME = ".env";

const PATH_SEGMENT_RE = /^[a-zA-Z0-9_-]+$/;

export function expandHomePrefix(value: string): string {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.resolve(os.homedir(), value.slice(2));
  return value;
}

export function resolveHermesFabricHomeDir(homeOverride?: string): string {
  const raw = homeOverride?.trim() || process.env.HERMES_FABRIC_HOME?.trim();
  if (raw) return path.resolve(expandHomePrefix(raw));
  return path.resolve(os.homedir(), ".fabric");
}

export function resolveHermesFabricInstanceId(instanceIdOverride?: string): string {
  const raw = instanceIdOverride?.trim() || process.env.HERMES_FABRIC_INSTANCE_ID?.trim() || DEFAULT_HERMES_FABRIC_INSTANCE_ID;
  if (!PATH_SEGMENT_RE.test(raw)) {
    throw new Error(`Invalid HERMES_FABRIC_INSTANCE_ID '${raw}'.`);
  }
  return raw;
}

export function resolveHermesFabricInstanceRoot(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricHomeDir(input.homeDir), "instances", resolveHermesFabricInstanceId(input.instanceId));
}

export function resolveHermesFabricInstanceConfigPath(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), HERMES_FABRIC_CONFIG_BASENAME);
}

export function resolveHermesFabricConfigPathForInstance(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return resolveHermesFabricInstanceConfigPath(input);
}

export function resolveHermesFabricEnvPathForConfig(configPath: string): string {
  return path.resolve(path.dirname(configPath), HERMES_FABRIC_ENV_FILENAME);
}

export function resolveDefaultEmbeddedPostgresDir(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), "db");
}

export function resolveDefaultLogsDir(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), "logs");
}

export function resolveDefaultSecretsKeyFilePath(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), "secrets", "master.key");
}

export function resolveDefaultStorageDir(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), "data", "storage");
}

export function resolveDefaultBackupDir(input: {
  homeDir?: string;
  instanceId?: string;
} = {}): string {
  return path.resolve(resolveHermesFabricInstanceRoot(input), "data", "backups");
}

export function resolveHomeAwarePath(value: string): string {
  return path.resolve(expandHomePrefix(value));
}
