/**
 * Hermes Fabric environment variable layer.
 *
 * HERMES_FABRIC_<name> is canonical. FABRIC_<name> remains a read-only
 * compatibility alias for installations created during the earlier rename.
 * Writes publish only the canonical key so child processes receive one
 * unambiguous value.
 */

export function fabricEnv(name: string): string | undefined {
  return process.env[`HERMES_FABRIC_${name}`] ?? process.env[`FABRIC_${name}`];
}

export function fabricEnvSet(name: string, value: string): void {
  process.env[`HERMES_FABRIC_${name}`] = value;
}

export function fabricEnvDefined(name: string): boolean {
  return (
    process.env[`HERMES_FABRIC_${name}`] !== undefined ||
    process.env[`FABRIC_${name}`] !== undefined
  );
}
