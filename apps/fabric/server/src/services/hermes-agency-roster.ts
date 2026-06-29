import { access, readFile } from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import os from "node:os";
import path from "node:path";
import type { HermesAgencyAgent, HermesAgencyAgentStatus, HermesAgencyRosterResponse } from "@paperclipai/shared";

export class HermesAgencyRosterUnavailableError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "HermesAgencyRosterUnavailableError";
  }
}

interface RawRosterProfile {
  name?: unknown;
  description?: unknown;
  skills?: unknown;
  capabilities?: unknown;
  online?: unknown;
  last_seen?: unknown;
  wake_attempt_count?: unknown;
  last_wake_attempt_at?: unknown;
  last_wake_error?: unknown;
  model?: unknown;
  provider?: unknown;
}

interface RawRosterState {
  tenant?: unknown;
  filter?: unknown;
  profiles?: unknown;
}

export interface HermesAgencyRosterServiceOptions {
  rosterPath?: string;
}

function defaultRosterPath() {
  return path.join(os.homedir(), ".hermes", ".agency", "roster_state.json");
}

export function resolveHermesAgencyRosterPath(options: HermesAgencyRosterServiceOptions = {}) {
  return options.rosterPath
    ?? process.env.HERMES_AGENCY_ROSTER_PATH?.trim()
    ?? defaultRosterPath();
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .map((item) => item.trim()),
    ),
  );
}

function skillsFromCapabilities(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value
        .map((capability) => {
          if (!capability || typeof capability !== "object") return null;
          return asString((capability as { id?: unknown }).id);
        })
        .filter((item): item is string => Boolean(item)),
    ),
  );
}

function asCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return 0;
  return Math.floor(value);
}

function statusFor(input: { online: boolean; lastError: string | null }): HermesAgencyAgentStatus {
  if (input.online) return "online";
  if (input.lastError) return "wake_failed";
  return "offline";
}

function isRosterTargetAgent(name: string) {
  // Hermes Fabric's operator roster shows the delegable agency workforce. The
  // orchestration profile is runtime infrastructure, not a specialist target.
  return name !== "agency-orchestrator";
}

export function normalizeHermesAgencyRoster(raw: RawRosterState): HermesAgencyRosterResponse {
  const profiles = Array.isArray(raw.profiles) ? raw.profiles as RawRosterProfile[] : [];
  const agents: HermesAgencyAgent[] = profiles
    .map((profile) => {
      const name = asString(profile.name);
      if (!name || !isRosterTargetAgent(name)) return null;
      const skills = asStringArray(profile.skills);
      const fallbackSkills = skillsFromCapabilities(profile.capabilities);
      const online = profile.online === true;
      const lastError = asString(profile.last_wake_error);
      return {
        name,
        description: asString(profile.description) ?? "",
        skills: skills.length > 0 ? skills : fallbackSkills,
        online,
        status: statusFor({ online, lastError }),
        lastSeen: asString(profile.last_seen),
        wakeAttempts: asCount(profile.wake_attempt_count),
        lastAttempt: asString(profile.last_wake_attempt_at),
        lastError,
        model: asString(profile.model),
        provider: asString(profile.provider),
      };
    })
    .filter((agent): agent is HermesAgencyAgent => agent !== null)
    .sort((a, b) => a.name.localeCompare(b.name));

  const online = agents.filter((agent) => agent.online).length;
  return {
    tenant: asString(raw.tenant) ?? "default",
    filter: asString(raw.filter) ?? "agency-only",
    total: agents.length,
    online,
    offline: agents.length - online,
    agents,
  };
}

export async function readHermesAgencyRoster(
  options: HermesAgencyRosterServiceOptions = {},
): Promise<HermesAgencyRosterResponse> {
  const rosterPath = resolveHermesAgencyRosterPath(options);
  try {
    await access(rosterPath, fsConstants.R_OK);
  } catch (error) {
    throw new HermesAgencyRosterUnavailableError(`Hermes Agency roster state is unavailable at ${rosterPath}`, {
      cause: error,
    });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(await readFile(rosterPath, "utf8"));
  } catch (error) {
    throw new HermesAgencyRosterUnavailableError(`Hermes Agency roster state could not be read from ${rosterPath}`, {
      cause: error,
    });
  }

  if (!parsed || typeof parsed !== "object") {
    throw new HermesAgencyRosterUnavailableError(`Hermes Agency roster state at ${rosterPath} is not a JSON object`);
  }

  return normalizeHermesAgencyRoster(parsed as RawRosterState);
}
