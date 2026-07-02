import { z } from "zod";

export const MODEL_SET_SOURCES = ["custom", "packaged"] as const;
export const MODEL_PRICING_TYPES = ["api", "subscription", "local", "manual"] as const;

export const modelFamilySchema = z.object({
  provider: z.string().trim().min(1).max(120),
  model: z.string().trim().min(1).max(240),
  reason: z.string().trim().min(1).max(500).optional(),
});

export const modelBudgetSchema = z.object({
  max_input_cost_per_1m: z.number().finite().nullable().optional(),
  max_output_cost_per_1m: z.number().finite().nullable().optional(),
  warn_if_unknown_pricing: z.boolean().optional(),
});

export const modelEscalationSchema = z.object({
  default_family: z.string().trim().min(1).max(120).optional(),
  triggers: z.array(z.string().trim().min(1).max(120)).optional().default([]),
});

export const modelSetDefinitionSchema = z.object({
  version: z.number().int().positive().optional().default(1),
  name: z.string().trim().min(1).max(120),
  description: z.string().trim().min(1).max(500).optional(),
  defaults: z.object({
    family: z.string().trim().min(1).max(120),
  }),
  families: z.record(z.string().trim().min(1).max(120), modelFamilySchema),
  profiles: z.record(z.string().trim().min(1).max(240), z.string().trim().min(1).max(120)).default({}),
  escalation: modelEscalationSchema.optional(),
  budget: modelBudgetSchema.optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export const modelSetDefinitionPatchSchema = z.object({
  version: z.number().int().positive().optional(),
  name: z.string().trim().min(1).max(120).optional(),
  description: z.string().trim().min(1).max(500).optional().nullable(),
  defaults: z.object({
    family: z.string().trim().min(1).max(120),
  }).optional(),
  families: z.record(z.string().trim().min(1).max(120), modelFamilySchema).optional(),
  profiles: z.record(z.string().trim().min(1).max(240), z.string().trim().min(1).max(120)).optional(),
  escalation: modelEscalationSchema.optional(),
  budget: modelBudgetSchema.optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export const modelSetCompanyQuerySchema = z.object({
  companyId: z.string().uuid(),
});

export const createModelSetSchema = z.object({
  companyId: z.string().uuid(),
  description: z.string().trim().min(1).max(500).nullable().optional(),
  createdBy: z.string().trim().min(1).max(255).optional(),
  definition: modelSetDefinitionSchema,
});

export const updateModelSetSchema = z.object({
  companyId: z.string().uuid(),
  description: z.string().trim().min(1).max(500).nullable().optional(),
  updatedBy: z.string().trim().min(1).max(255).optional(),
  definition: modelSetDefinitionPatchSchema.optional(),
});

export const applyModelSetSchema = z.object({
  companyId: z.string().uuid(),
  appliedBy: z.string().trim().min(1).max(255).optional(),
});

export const modelDepartmentOverrideSchema = z.object({
  department: z.string().trim().min(1).max(120),
  provider: z.string().trim().min(1).max(120),
  model: z.string().trim().min(1).max(240),
  reason: z.string().trim().min(1).max(500).nullable().optional(),
});

export const putDepartmentOverridesSchema = z.object({
  companyId: z.string().uuid(),
  overrides: z.array(modelDepartmentOverrideSchema),
});

export const upsertProfileOverrideSchema = z.object({
  companyId: z.string().uuid(),
  provider: z.string().trim().min(1).max(120),
  model: z.string().trim().min(1).max(240),
  reason: z.string().trim().min(1).max(500).nullable().optional(),
});

export const deleteProfileOverrideQuerySchema = z.object({
  companyId: z.string().uuid(),
});

export const modelPricingItemSchema = z.object({
  provider: z.string().trim().min(1).max(120),
  model: z.string().trim().min(1).max(240),
  inputCostPer1m: z.number().finite().nullable().optional(),
  outputCostPer1m: z.number().finite().nullable().optional(),
  pricingType: z.enum(MODEL_PRICING_TYPES),
  monthlyEstimate: z.number().finite().nullable().optional(),
});

export const putModelPricingSchema = z.object({
  items: z.array(modelPricingItemSchema),
});

export type ModelFamily = z.infer<typeof modelFamilySchema>;
export type ModelBudget = z.infer<typeof modelBudgetSchema>;
export type ModelEscalation = z.infer<typeof modelEscalationSchema>;
export type ModelSetDefinition = z.infer<typeof modelSetDefinitionSchema>;
export type ModelSetDefinitionPatch = z.infer<typeof modelSetDefinitionPatchSchema>;
export type CreateModelSet = z.infer<typeof createModelSetSchema>;
export type UpdateModelSet = z.infer<typeof updateModelSetSchema>;
export type ApplyModelSet = z.infer<typeof applyModelSetSchema>;
export type ModelDepartmentOverrideInput = z.infer<typeof modelDepartmentOverrideSchema>;
export type PutDepartmentOverrides = z.infer<typeof putDepartmentOverridesSchema>;
export type UpsertProfileOverride = z.infer<typeof upsertProfileOverrideSchema>;
export type ModelPricingItem = z.infer<typeof modelPricingItemSchema>;
export type PutModelPricing = z.infer<typeof putModelPricingSchema>;
