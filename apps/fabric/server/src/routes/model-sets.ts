import { Router } from "express";
import type { Db } from "@hermes-fabric/db";
import {
  applyModelSetSchema,
  createModelSetSchema,
  deleteProfileOverrideQuerySchema,
  modelSetCompanyQuerySchema,
  putDepartmentOverridesSchema,
  putModelPricingSchema,
  updateModelSetSchema,
  upsertProfileOverrideSchema,
} from "@hermes-fabric/shared";
import { badRequest } from "../errors.js";
import { validate } from "../middleware/validate.js";
import { logActivity, modelSetService } from "../services/index.js";
import { assertBoardOrgAccess, assertCompanyAccess, getActorInfo } from "./authz.js";

function stringQuery(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw badRequest(`${label} is required`);
  }
  return value.trim();
}

export function modelSetRoutes(db: Db) {
  const router = Router();
  const svc = modelSetService(db);

  router.get("/model-sets", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.listModelSets(query.companyId));
  });

  router.get("/model-sets/:name", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    const name = String(req.params.name);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.getModelSet(query.companyId, name));
  });

  router.post("/model-sets", validate(createModelSetSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const body = createModelSetSchema.parse(req.body);
    assertCompanyAccess(req, body.companyId);
    const actor = getActorInfo(req);
    const created = await svc.createModelSet(body.companyId, {
      definition: body.definition,
      description: body.description,
      createdBy: body.createdBy ?? actor.actorId,
    });
    await logActivity(db, {
      companyId: body.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_set.created",
      entityType: "model_set",
      entityId: created.id,
      details: { name: created.name, source: created.source },
    });
    res.status(201).json(created);
  });

  router.put("/model-sets/:name", validate(updateModelSetSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const name = String(req.params.name);
    const body = updateModelSetSchema.parse(req.body);
    assertCompanyAccess(req, body.companyId);
    const actor = getActorInfo(req);
    const updated = await svc.updateModelSet(body.companyId, name, {
      definition: body.definition,
      description: body.description,
      updatedBy: body.updatedBy ?? actor.actorId,
    });
    await logActivity(db, {
      companyId: body.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_set.updated",
      entityType: "model_set",
      entityId: updated.id,
      details: { name: updated.name, changedKeys: Object.keys(body).sort() },
    });
    res.json(updated);
  });

  router.delete("/model-sets/:name", async (req, res) => {
    assertBoardOrgAccess(req);
    const name = String(req.params.name);
    const companyId = stringQuery(req.query.companyId, "companyId");
    assertCompanyAccess(req, companyId);
    const actor = getActorInfo(req);
    const result = await svc.deleteModelSet(companyId, name);
    await logActivity(db, {
      companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_set.deleted",
      entityType: "model_set",
      entityId: name,
      details: result,
    });
    res.json(result);
  });

  router.get("/model-sets/:name/preview", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    const name = String(req.params.name);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.previewApply(query.companyId, name));
  });

  router.post("/model-sets/:name/apply", validate(applyModelSetSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const name = String(req.params.name);
    const body = applyModelSetSchema.parse(req.body);
    assertCompanyAccess(req, body.companyId);
    const actor = getActorInfo(req);
    const result = await svc.applyModelSet(body.companyId, name, {
      appliedBy: body.appliedBy ?? actor.actorId,
      restartIdleGateways: body.restartIdleGateways,
    });
    await logActivity(db, {
      companyId: body.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_set.applied",
      entityType: "model_set",
      entityId: name,
      details: {
        changedAgents: result.changedAgents,
        name: result.name,
        profileConfigs: result.profileConfigs,
        agentChanges: result.agentChanges,
        gatewayRestart: result.gatewayRestart,
        restartIdleGateways: body.restartIdleGateways,
      },
    });
    res.json(result);
  });

  router.get("/model-overrides/department", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.listDepartmentOverrides(query.companyId));
  });

  router.put("/model-overrides/department", validate(putDepartmentOverridesSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const body = putDepartmentOverridesSchema.parse(req.body);
    assertCompanyAccess(req, body.companyId);
    const actor = getActorInfo(req);
    const result = await svc.replaceDepartmentOverrides(body.companyId, body.overrides);
    await logActivity(db, {
      companyId: body.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_override.department_replaced",
      entityType: "model_department_override",
      entityId: body.companyId,
      details: { count: result.length },
    });
    res.json(result);
  });

  router.get("/model-overrides/profile", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.listProfileOverrides(query.companyId));
  });

  router.put("/model-overrides/profile/:agentId", validate(upsertProfileOverrideSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const agentId = String(req.params.agentId);
    const body = upsertProfileOverrideSchema.parse(req.body);
    assertCompanyAccess(req, body.companyId);
    const actor = getActorInfo(req);
    const result = await svc.upsertProfileOverride(body.companyId, agentId, body);
    await logActivity(db, {
      companyId: body.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_override.profile_upserted",
      entityType: "model_profile_override",
      entityId: agentId,
      details: { provider: result.provider, model: result.model, reasoningEffort: result.reasoningEffort ?? null },
    });
    res.json(result);
  });

  router.delete("/model-overrides/profile/:agentId", async (req, res) => {
    assertBoardOrgAccess(req);
    const agentId = String(req.params.agentId);
    const query = deleteProfileOverrideQuerySchema.parse(req.query);
    assertCompanyAccess(req, query.companyId);
    const actor = getActorInfo(req);
    const result = await svc.deleteProfileOverride(query.companyId, agentId);
    await logActivity(db, {
      companyId: query.companyId,
      actorType: actor.actorType,
      actorId: actor.actorId,
      agentId: actor.agentId,
      runId: actor.runId,
      action: "model_override.profile_deleted",
      entityType: "model_profile_override",
      entityId: agentId,
      details: result,
    });
    res.json(result);
  });

  router.get("/model-pricing", async (req, res) => {
    assertBoardOrgAccess(req);
    res.json(await svc.listPricing());
  });

  router.put("/model-pricing", validate(putModelPricingSchema), async (req, res) => {
    assertBoardOrgAccess(req);
    const body = putModelPricingSchema.parse(req.body);
    const actor = getActorInfo(req);
    const result = await svc.upsertPricing(body.items);
    const companyIds = req.actor.companyIds ?? [];
    await Promise.all(
      companyIds.map((companyId) =>
        logActivity(db, {
          companyId,
          actorType: actor.actorType,
          actorId: actor.actorId,
          agentId: actor.agentId,
          runId: actor.runId,
          action: "model_pricing.updated",
          entityType: "model_pricing",
          entityId: "global",
          details: { count: body.items.length },
        }),
      ),
    );
    res.json(result);
  });

  router.post("/model-pricing/auto-detect", async (req, res) => {
    assertBoardOrgAccess(req);
    const actor = getActorInfo(req);
    const result = await svc.autoDetectOpenRouterPricing();
    const companyIds = req.actor.companyIds ?? [];
    await Promise.all(
      companyIds.map((companyId) =>
        logActivity(db, {
          companyId,
          actorType: actor.actorType,
          actorId: actor.actorId,
          agentId: actor.agentId,
          runId: actor.runId,
          action: "model_pricing.auto_detected",
          entityType: "model_pricing",
          entityId: "openrouter",
          details: { discovered: result.discovered, upserted: result.upserted },
        }),
      ),
    );
    res.json(result);
  });

  router.get("/model-cost-estimate", async (req, res) => {
    assertBoardOrgAccess(req);
    const query = modelSetCompanyQuerySchema.parse(req.query);
    assertCompanyAccess(req, query.companyId);
    res.json(await svc.costEstimate(query.companyId));
  });

  return router;
}
