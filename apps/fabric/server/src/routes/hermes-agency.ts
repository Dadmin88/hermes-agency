import { Router } from "express";
import type { Db } from "@hermes-fabric/db";
import { agents } from "@hermes-fabric/db";
import { eq } from "drizzle-orm";
import { buildHermesAgencyTaskPacketPreview } from "@hermes-fabric/shared";
import { assertAuthenticated, assertCompanyAccess, assertInstanceAdmin } from "./authz.js";
import { forbidden } from "../errors.js";
import { authorizationService } from "../services/authorization.js";
import { resolveHermesProfileName } from "../services/hermes-profile-config.js";
import { dispatchHermesAgencyTask, getHermesAgencyDispatch, HermesAgencyDispatchUnavailableError, type HermesAgencyDispatchServiceOptions } from "../services/hermes-agency-dispatch.js";
import { HermesAgencyRosterUnavailableError, readHermesAgencyRoster, type HermesAgencyRosterServiceOptions } from "../services/hermes-agency-roster.js";
import { SharedSkillPoolError, createSharedPoolSkill, deleteSharedPoolSkill, effectiveProfileSkills, getProfileLocalSkill, getSharedPoolSkill, listSharedPool, setProfilePoolSkill, updateProfileLocalSkill, updateSharedPoolSkill, type SharedSkillPoolOptions } from "../services/shared-skill-pool.js";

type AgencyRouteOptions = HermesAgencyRosterServiceOptions & HermesAgencyDispatchServiceOptions & SharedSkillPoolOptions & { db?: Db };
export function hermesAgencyRoutes(options: AgencyRouteOptions = {}) {
  const router = Router();
  const poolError = (res: import("express").Response, error: unknown) => {
    if (!(error instanceof SharedSkillPoolError)) throw error;
    res.status(error.code === "not_found" ? 404 : error.code === "conflict" ? 409 : 422).json({ error: `shared_skill_pool_${error.code}`, message: error.message, ...(error.impact ? { impact: { count: error.impact.profiles.length, profiles: error.impact.profiles } } : {}) });
  };
  const canManageSharedPool = (req: import("express").Request) => (
    req.actor.type === "board" && (req.actor.isInstanceAdmin || req.actor.source === "local_implicit")
  );
  async function agentProfile(req: import("express").Request, agentId: string, mutate = false) {
    if (!options.db) throw new SharedSkillPoolError("Agent-scoped skill control is unavailable.", "not_found");
    const agent = await options.db.select().from(agents).where(eq(agents.id, agentId)).then((rows) => rows[0] ?? null);
    if (!agent) throw new SharedSkillPoolError("Agent was not found.", "not_found");
    assertCompanyAccess(req, agent.companyId);
    if (mutate && !(req.actor.type === "board" && (req.actor.isInstanceAdmin || req.actor.source === "local_implicit"))) {
      const decision = await authorizationService(options.db).decide({ actor: req.actor, action: "agent_config:update", resource: { type: "agent", companyId: agent.companyId, agentId: agent.id } });
      if (!decision.allowed) throw forbidden(decision.explanation);
    }
    const profile = resolveHermesProfileName(agent);
    if (!profile) throw new SharedSkillPoolError("Agent has no Hermes profile mapping.", "not_found");
    // Validate before filesystem access; do not trust adapter configuration as a path.
    if (profile === "." || profile === ".." || /[\\/]/.test(profile)) throw new SharedSkillPoolError("Agent Hermes profile mapping is invalid.");
    return { agent, profile };
  }
  router.get("/shared-skills", async (req, res) => { assertAuthenticated(req); try { res.json({ skills: await listSharedPool(options), canManage: canManageSharedPool(req) }); } catch (error) { poolError(res, error); } });
  // Skill source files may include preserved operator-managed scripts and references.
  // Metadata is authenticated-readable above, but source content is instance-admin-only.
  router.get("/shared-skills/:name", async (req, res) => { assertInstanceAdmin(req); try { res.json(await getSharedPoolSkill(req.params.name, options)); } catch (error) { poolError(res, error); } });
  router.post("/shared-skills", async (req, res) => { assertInstanceAdmin(req); try { res.status(201).json(await createSharedPoolSkill(req.body, options)); } catch (error) { poolError(res, error); } });
  router.put("/shared-skills/:name", async (req, res) => { assertInstanceAdmin(req); try { res.json(await updateSharedPoolSkill(req.params.name, req.body, options)); } catch (error) { poolError(res, error); } });
  router.delete("/shared-skills/:name", async (req, res) => { assertInstanceAdmin(req); try { res.json(await deleteSharedPoolSkill(req.params.name, req.query.confirm === "true", options)); } catch (error) { poolError(res, error); } });
  // Retained global profile routes intentionally remain instance-admin-only.
  router.get("/profiles/:profile/skills", async (req, res) => { assertInstanceAdmin(req); try { res.json({ profile: req.params.profile, skills: await effectiveProfileSkills(req.params.profile, options) }); } catch (error) { poolError(res, error); } });
  router.post("/profiles/:profile/skills/:name", async (req, res) => { assertInstanceAdmin(req); try { res.json({ profile: req.params.profile, skills: await setProfilePoolSkill(req.params.profile, req.params.name, true, options) }); } catch (error) { poolError(res, error); } });
  router.delete("/profiles/:profile/skills/:name", async (req, res) => { assertInstanceAdmin(req); try { res.json({ profile: req.params.profile, skills: await setProfilePoolSkill(req.params.profile, req.params.name, false, options) }); } catch (error) { poolError(res, error); } });
  // Client-safe agent-scoped operations: resolve the profile only after company and update checks.
  router.get("/agents/:agentId/skills", async (req, res) => { try { const target = await agentProfile(req, req.params.agentId); res.json({ agentId: target.agent.id, skills: await effectiveProfileSkills(target.profile, options) }); } catch (error) { poolError(res, error); } });
  router.post("/agents/:agentId/skills/:name", async (req, res) => { try { const target = await agentProfile(req, req.params.agentId, true); res.json({ agentId: target.agent.id, skills: await setProfilePoolSkill(target.profile, req.params.name, true, options) }); } catch (error) { poolError(res, error); } });
  router.delete("/agents/:agentId/skills/:name", async (req, res) => { try { const target = await agentProfile(req, req.params.agentId, true); res.json({ agentId: target.agent.id, skills: await setProfilePoolSkill(target.profile, req.params.name, false, options) }); } catch (error) { poolError(res, error); } });
  router.get("/agents/:agentId/skills/:name/local", async (req, res) => { try { const target = await agentProfile(req, req.params.agentId); res.json(await getProfileLocalSkill(target.profile, req.params.name, options)); } catch (error) { poolError(res, error); } });
  router.put("/agents/:agentId/skills/:name/local", async (req, res) => { try { const target = await agentProfile(req, req.params.agentId, true); res.json(await updateProfileLocalSkill(target.profile, req.params.name, req.body, options)); } catch (error) { poolError(res, error); } });
  router.get("/roster", async (req, res) => { assertInstanceAdmin(req); try { res.json(await readHermesAgencyRoster(options)); } catch (error) { if (error instanceof HermesAgencyRosterUnavailableError) { res.status(503).json({ error: "hermes_agency_roster_unavailable", message: error.message }); return; } throw error; } });
  router.post("/task-packet-preview", (req, res) => { assertInstanceAdmin(req); const body = req.body as { issue?: { title?: unknown }; requestedSkills?: string[]; targetAgentName?: string | null; validationExpectations?: string[]; artifactExpectations?: string[]; stopConditions?: string[] }; if (!body?.issue || typeof body.issue.title !== "string" || !body.issue.title.trim()) { res.status(400).json({ error: "invalid_hermes_agency_task_packet_preview", message: "issue.title is required" }); return; } res.json(buildHermesAgencyTaskPacketPreview({ issue: body.issue as never, requestedSkills: body.requestedSkills, targetAgentName: body.targetAgentName, validationExpectations: body.validationExpectations, artifactExpectations: body.artifactExpectations, stopConditions: body.stopConditions })); });
  router.post("/dispatch", async (req, res) => { assertInstanceAdmin(req); const body = req.body as { packet?: unknown; mode?: "skill-fit" | "direct-agent" }; const packet = body.packet as Parameters<typeof dispatchHermesAgencyTask>[0] | undefined; if (!packet || typeof packet !== "object" || typeof packet.title !== "string") { res.status(400).json({ error: "invalid_hermes_agency_dispatch", message: "packet.title is required" }); return; } try { res.status(202).json(await dispatchHermesAgencyTask(packet, body.mode, options)); } catch (error) { if (error instanceof HermesAgencyDispatchUnavailableError) { res.status(503).json({ error: "hermes_agency_dispatch_unavailable", message: error.message }); return; } throw error; } });
  router.get("/dispatches/:id", async (req, res) => { assertInstanceAdmin(req); const record = await getHermesAgencyDispatch(req.params.id, options); if (!record) { res.status(404).json({ error: "hermes_agency_dispatch_not_found" }); return; } res.json(record); });
  return router;
}
