import { Router, type Request } from "express";
import type { Db } from "@paperclipai/db";
import { buildHermesAgencyTaskPacketPreview } from "@paperclipai/shared";
import { assertBoard, assertCompanyAccess } from "./authz.js";
import {
  getHermesKanbanProjectionStatus,
  resolveHermesKanbanCompanyId,
} from "../services/hermes-kanban-issues.js";
import {
  dispatchHermesAgencyTask,
  getHermesAgencyDispatch,
  HermesAgencyDispatchUnavailableError,
  type HermesAgencyDispatchServiceOptions,
} from "../services/hermes-agency-dispatch.js";
import {
  HermesAgencyRosterUnavailableError,
  readHermesAgencyRoster,
  type HermesAgencyRosterServiceOptions,
} from "../services/hermes-agency-roster.js";

const DEFAULT_KERYX_RELAY_HEALTH_URL = "http://127.0.0.1:18081/health";
const DEFAULT_KERYX_RELAY_TIMEOUT_MS = 750;
const KERYX_ONE_WAY_COMPLETION_LIMITATION =
  "Keryx relay completion responses are currently one-way: the VPS sender may time out because the relay completion return path is not implemented, even when the remote Katana worker completes successfully.";

export interface HermesAgencyKeryxStatusOptions {
  keryxHealthUrl?: string;
  keryxHealthTimeoutMs?: number;
  keryxHealthFetch?: typeof fetch;
}

export function hermesAgencyRoutes(
  db: Db,
  options: HermesAgencyRosterServiceOptions & HermesAgencyDispatchServiceOptions & HermesAgencyKeryxStatusOptions = {},
) {
  void db;
  const router = Router();

  router.get("/kanban-projection/status", async (req, res) => {
    const companyId = resolveHermesKanbanCompanyId();
    assertHermesKanbanProjectionStatusAccess(req, companyId);
    res.json(getHermesKanbanProjectionStatus());
  });

  router.get("/roster", async (req, res) => {
    assertBoard(req);
    try {
      res.json(await readHermesAgencyRoster(options));
    } catch (error) {
      if (error instanceof HermesAgencyRosterUnavailableError) {
        res.status(503).json({
          error: "hermes_agency_roster_unavailable",
          message: error.message,
        });
        return;
      }
      throw error;
    }
  });

  router.get("/keryx/status", async (req, res) => {
    assertBoard(req);
    res.json(await readKeryxTransportStatus(options));
  });

  router.post("/task-packet-preview", (req, res) => {
    assertBoard(req);
    const body = req.body as {
      issue?: { title?: unknown };
      requestedSkills?: string[];
      targetAgentName?: string | null;
      validationExpectations?: string[];
      artifactExpectations?: string[];
      stopConditions?: string[];
    };

    if (!body?.issue || typeof body.issue.title !== "string" || body.issue.title.trim().length === 0) {
      res.status(400).json({
        error: "invalid_hermes_agency_task_packet_preview",
        message: "issue.title is required",
      });
      return;
    }

    res.json(buildHermesAgencyTaskPacketPreview({
      issue: body.issue as never,
      requestedSkills: body.requestedSkills,
      targetAgentName: body.targetAgentName,
      validationExpectations: body.validationExpectations,
      artifactExpectations: body.artifactExpectations,
      stopConditions: body.stopConditions,
    }));
  });

  router.post("/dispatch", async (req, res) => {
    assertBoard(req);
    const body = req.body as {
      packet?: unknown;
      mode?: "skill-fit" | "direct-agent";
    };
    const packet = body.packet as Parameters<typeof dispatchHermesAgencyTask>[0] | undefined;
    if (!packet || typeof packet !== "object" || typeof packet.title !== "string") {
      res.status(400).json({
        error: "invalid_hermes_agency_dispatch",
        message: "packet.title is required",
      });
      return;
    }
    try {
      const record = await dispatchHermesAgencyTask(packet, body.mode, options);
      res.status(202).json(record);
    } catch (error) {
      if (error instanceof HermesAgencyDispatchUnavailableError) {
        res.status(503).json({
          error: "hermes_agency_dispatch_unavailable",
          message: error.message,
        });
        return;
      }
      throw error;
    }
  });

  router.get("/dispatches/:id", async (req, res) => {
    assertBoard(req);
    const record = await getHermesAgencyDispatch(req.params.id, options);
    if (!record) {
      res.status(404).json({ error: "hermes_agency_dispatch_not_found" });
      return;
    }
    res.json(record);
  });

  return router;
}

function assertHermesKanbanProjectionStatusAccess(req: Request, companyId: string | null) {
  assertBoard(req);
  if (!companyId) return;
  if (req.actor.source === "local_implicit" || req.actor.isInstanceAdmin) return;
  assertCompanyAccess(req, companyId);
}

async function readKeryxTransportStatus(options: HermesAgencyKeryxStatusOptions) {
  const healthUrl = options.keryxHealthUrl ?? DEFAULT_KERYX_RELAY_HEALTH_URL;
  const timeoutMs = options.keryxHealthTimeoutMs ?? DEFAULT_KERYX_RELAY_TIMEOUT_MS;
  const fetchImpl = options.keryxHealthFetch ?? fetch;
  const startedAt = Date.now();

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(healthUrl, { signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      return buildKeryxTransportStatus({
        healthy: false,
        relayReachable: true,
        checkedUrl: healthUrl,
        checkedAt: new Date().toISOString(),
        latencyMs: Date.now() - startedAt,
        error: `Keryx relay health returned HTTP ${response.status}`,
      });
    }

    const raw = await response.json() as Record<string, unknown>;
    return buildKeryxTransportStatus({
      healthy: inferKeryxHealthy(raw),
      relayReachable: true,
      checkedUrl: healthUrl,
      checkedAt: new Date().toISOString(),
      latencyMs: Date.now() - startedAt,
      connectedPeers: readOptionalNumber(raw, "connectedPeers", "connected_peers", "peers", "peerCount", "peer_count"),
      registrySize: readOptionalNumber(raw, "registrySize", "registry_size", "registeredAgents", "registered_agents"),
      tasksRouted: readOptionalNumber(raw, "tasksRouted", "tasks_routed", "routedTasks", "routed_tasks"),
      raw,
    });
  } catch (error) {
    return buildKeryxTransportStatus({
      healthy: false,
      relayReachable: false,
      checkedUrl: healthUrl,
      checkedAt: new Date().toISOString(),
      latencyMs: Date.now() - startedAt,
      error: error instanceof Error && error.name === "AbortError"
        ? `Keryx relay health timed out after ${timeoutMs}ms`
        : error instanceof Error
          ? error.message
          : "Keryx relay health is unreachable",
    });
  }
}

function buildKeryxTransportStatus(input: {
  healthy: boolean;
  relayReachable: boolean;
  checkedUrl: string;
  checkedAt: string;
  latencyMs: number;
  connectedPeers?: number;
  registrySize?: number;
  tasksRouted?: number;
  error?: string;
  raw?: Record<string, unknown>;
}) {
  return {
    healthy: input.healthy,
    relayReachable: input.relayReachable,
    connectedPeers: input.connectedPeers ?? null,
    registrySize: input.registrySize ?? null,
    tasksRouted: input.tasksRouted ?? null,
    checkedAt: input.checkedAt,
    checkedUrl: input.checkedUrl,
    latencyMs: input.latencyMs,
    knownLimitations: {
      oneWayCompletionResponse: true,
      message: KERYX_ONE_WAY_COMPLETION_LIMITATION,
    },
    error: input.error ?? null,
    raw: input.raw ?? null,
  };
}

function inferKeryxHealthy(raw: Record<string, unknown>) {
  if (typeof raw.healthy === "boolean") return raw.healthy;
  if (typeof raw.ok === "boolean") return raw.ok;
  if (typeof raw.status === "string") {
    const status = raw.status.toLowerCase();
    return status === "ok" || status === "healthy" || status === "up";
  }
  return true;
}

function readOptionalNumber(raw: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}
