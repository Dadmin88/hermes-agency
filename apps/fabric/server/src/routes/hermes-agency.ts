import { Router } from "express";
import { buildHermesAgencyTaskPacketPreview } from "@hermes-fabric/shared";
import { assertBoard } from "./authz.js";
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

export function hermesAgencyRoutes(options: HermesAgencyRosterServiceOptions & HermesAgencyDispatchServiceOptions = {}) {
  const router = Router();

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
