import {
  doublePrecision,
  index,
  jsonb,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";
import { agents } from "./agents.js";
import { companies } from "./companies.js";

export const modelSets = pgTable(
  "model_sets",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id")
      .notNull()
      .references(() => companies.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    description: text("description"),
    source: text("source").notNull().default("custom"),
    definition: jsonb("definition").$type<Record<string, unknown>>().notNull().default({}),
    createdBy: text("created_by").notNull().default("system"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("model_sets_company_idx").on(table.companyId),
    companyNameUq: uniqueIndex("model_sets_company_name_uq").on(table.companyId, table.name),
  }),
);

export const modelDepartmentOverrides = pgTable(
  "model_department_overrides",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id")
      .notNull()
      .references(() => companies.id, { onDelete: "cascade" }),
    department: text("department").notNull(),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    reason: text("reason"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("model_department_overrides_company_idx").on(table.companyId),
    companyDepartmentUq: uniqueIndex("model_department_overrides_company_department_uq").on(
      table.companyId,
      table.department,
    ),
  }),
);

export const modelProfileOverrides = pgTable(
  "model_profile_overrides",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    companyId: uuid("company_id")
      .notNull()
      .references(() => companies.id, { onDelete: "cascade" }),
    agentId: uuid("agent_id")
      .notNull()
      .references(() => agents.id, { onDelete: "cascade" }),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    reason: text("reason"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    companyIdx: index("model_profile_overrides_company_idx").on(table.companyId),
    agentIdx: index("model_profile_overrides_agent_idx").on(table.agentId),
    companyAgentUq: uniqueIndex("model_profile_overrides_company_agent_uq").on(
      table.companyId,
      table.agentId,
    ),
  }),
);

export const modelPricing = pgTable(
  "model_pricing",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    inputCostPer1m: doublePrecision("input_cost_per_1m"),
    outputCostPer1m: doublePrecision("output_cost_per_1m"),
    pricingType: text("pricing_type").notNull().default("manual"),
    monthlyEstimate: doublePrecision("monthly_estimate"),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    providerIdx: index("model_pricing_provider_idx").on(table.provider),
    providerModelUq: uniqueIndex("model_pricing_provider_model_uq").on(table.provider, table.model),
  }),
);
