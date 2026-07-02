CREATE TABLE IF NOT EXISTS "model_sets" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"source" text DEFAULT 'custom' NOT NULL,
	"definition" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_by" text DEFAULT 'system' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "model_sets" ADD CONSTRAINT "model_sets_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "model_sets_company_idx" ON "model_sets" USING btree ("company_id");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "model_sets_company_name_uq" ON "model_sets" USING btree ("company_id","name");
--> statement-breakpoint

CREATE TABLE IF NOT EXISTS "model_department_overrides" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"department" text NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"reason" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "model_department_overrides" ADD CONSTRAINT "model_department_overrides_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "model_department_overrides_company_idx" ON "model_department_overrides" USING btree ("company_id");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "model_department_overrides_company_department_uq" ON "model_department_overrides" USING btree ("company_id","department");
--> statement-breakpoint

CREATE TABLE IF NOT EXISTS "model_profile_overrides" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"company_id" uuid NOT NULL,
	"agent_id" uuid NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"reason" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "model_profile_overrides" ADD CONSTRAINT "model_profile_overrides_company_id_companies_id_fk" FOREIGN KEY ("company_id") REFERENCES "public"."companies"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
DO $$ BEGIN
 ALTER TABLE "model_profile_overrides" ADD CONSTRAINT "model_profile_overrides_agent_id_agents_id_fk" FOREIGN KEY ("agent_id") REFERENCES "public"."agents"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
 WHEN duplicate_object THEN null;
END $$;
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "model_profile_overrides_company_idx" ON "model_profile_overrides" USING btree ("company_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "model_profile_overrides_agent_idx" ON "model_profile_overrides" USING btree ("agent_id");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "model_profile_overrides_company_agent_uq" ON "model_profile_overrides" USING btree ("company_id","agent_id");
--> statement-breakpoint

CREATE TABLE IF NOT EXISTS "model_pricing" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"provider" text NOT NULL,
	"model" text NOT NULL,
	"input_cost_per_1m" double precision,
	"output_cost_per_1m" double precision,
	"pricing_type" text DEFAULT 'manual' NOT NULL,
	"monthly_estimate" double precision,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "model_pricing_provider_idx" ON "model_pricing" USING btree ("provider");
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "model_pricing_provider_model_uq" ON "model_pricing" USING btree ("provider","model");
