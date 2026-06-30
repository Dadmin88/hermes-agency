/**
 * Backward-compatible environment variable layer.
 *
 * During the PAPERCLIP → FABRIC branding rename the server reads
 * FABRIC_<name> first and falls back to PAPERCLIP_<name>.
 * Writes always set BOTH variants so that downstream code using either
 * prefix continues to work.
 */

export function fabricEnv(name: string): string | undefined {
  return process.env[`FABRIC_${name}`] ?? process.env[`PAPERCLIP_${name}`];
}

export function fabricEnvSet(name: string, value: string): void {
  process.env[`FABRIC_${name}`] = value;
  process.env[`PAPERCLIP_${name}`] = value;
}

export function fabricEnvDefined(name: string): boolean {
  return (
    process.env[`FABRIC_${name}`] !== undefined ||
    process.env[`PAPERCLIP_${name}`] !== undefined
  );
}
