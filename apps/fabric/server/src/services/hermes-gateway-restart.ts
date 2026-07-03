import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import { and, eq, inArray } from "drizzle-orm";
import { agents, heartbeatRuns } from "@paperclipai/db";
import type { Db } from "@paperclipai/db";
import { resolveHermesProfileName } from "./hermes-profile-config.js";

const execFileAsync = promisify(execFile);

const LIVE_HEARTBEAT_STATUSES = ["queued", "running"] as const;

export type GatewayRestartSkipReason =
  | "not_hermes_gateway"
  | "agent_running"
  | "live_heartbeat_run"
  | "no_profile"
  | "missing_api_key";

export type GatewayRestartResult = {
  attempted: Array<{ agentId: string; agentName: string; profile: string }>;
  skipped: Array<{ agentId: string; agentName: string; reason: GatewayRestartSkipReason; detail?: string }>;
  errors: Array<{ agentId: string; agentName: string; error: string }>;
};

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function resolveHermesCommand(adapterConfig: Record<string, unknown>): string {
  const command = adapterConfig.hermesCommand ?? adapterConfig.command;
  return typeof command === "string" && command.trim().length > 0 ? command.trim() : "hermes";
}

export type RestartHermesGatewayDeps = {
  restartGateway?: (input: {
    profileName: string;
    hermesCommand: string;
    apiKey: string | null;
  }) => Promise<void>;
};

export async function restartHermesGatewayProcess(input: {
  profileName: string;
  hermesCommand?: string;
  apiKey?: string | null;
}) {
  const command = input.hermesCommand?.trim() || "hermes";
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    HERMES_PROFILE: input.profileName,
    API_SERVER_ENABLED: "true",
  };
  if (input.apiKey) {
    env.API_SERVER_KEY = input.apiKey;
  }

  if (command === "hermes") {
    try {
      await execFileAsync("hermes", ["--version"], { timeout: 5_000 });
    } catch (error) {
      throw new Error(
        `Hermes CLI is not available for gateway restart (profile ${input.profileName}): ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  }

  await new Promise<void>((resolve, reject) => {
    const child = spawn(command, ["gateway", "run", "--replace", "--accept-hooks", "-q"], {
      detached: true,
      stdio: "ignore",
      env,
    });
    child.once("error", reject);
    child.unref();
    resolve();
  });
}

export async function restartIdleGateways(
  db: Db,
  companyId: string,
  input?: { agentIds?: string[]; deps?: RestartHermesGatewayDeps },
): Promise<GatewayRestartResult> {
  const result: GatewayRestartResult = { attempted: [], skipped: [], errors: [] };
  const restartGateway = input?.deps?.restartGateway ?? restartHermesGatewayProcess;

  const agentRows = await db
    .select()
    .from(agents)
    .where(eq(agents.companyId, companyId))
    .orderBy(agents.name);

  const gatewayAgents = agentRows.filter((row) => row.adapterType === "hermes_gateway");
  const selected =
    input?.agentIds && input.agentIds.length > 0
      ? gatewayAgents.filter((row) => input.agentIds!.includes(row.id))
      : gatewayAgents;

  if (selected.length === 0) {
    return result;
  }

  const liveRuns = await db
    .select({ agentId: heartbeatRuns.agentId })
    .from(heartbeatRuns)
    .where(
      and(
        eq(heartbeatRuns.companyId, companyId),
        inArray(heartbeatRuns.agentId, selected.map((row) => row.id)),
        inArray(heartbeatRuns.status, [...LIVE_HEARTBEAT_STATUSES]),
      ),
    );
  const liveAgentIds = new Set(liveRuns.map((row) => row.agentId));

  for (const agentRow of selected) {
    if (agentRow.status === "running") {
      result.skipped.push({
        agentId: agentRow.id,
        agentName: agentRow.name,
        reason: "agent_running",
      });
      continue;
    }
    if (liveAgentIds.has(agentRow.id)) {
      result.skipped.push({
        agentId: agentRow.id,
        agentName: agentRow.name,
        reason: "live_heartbeat_run",
      });
      continue;
    }

    const profileName = resolveHermesProfileName(agentRow);
    if (!profileName) {
      result.skipped.push({
        agentId: agentRow.id,
        agentName: agentRow.name,
        reason: "no_profile",
      });
      continue;
    }

    const adapterConfig = asRecord(agentRow.adapterConfig);
    const apiKey = typeof adapterConfig.apiKey === "string" ? adapterConfig.apiKey : null;
    const hermesCommand = resolveHermesCommand(adapterConfig);

    try {
      await restartGateway({ profileName, hermesCommand, apiKey });
      result.attempted.push({
        agentId: agentRow.id,
        agentName: agentRow.name,
        profile: profileName,
      });
    } catch (error) {
      result.errors.push({
        agentId: agentRow.id,
        agentName: agentRow.name,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  return result;
}