ALTER TABLE "model_department_overrides" ADD COLUMN IF NOT EXISTS "reasoning_effort" text;
--> statement-breakpoint
ALTER TABLE "model_profile_overrides" ADD COLUMN IF NOT EXISTS "reasoning_effort" text;
--> statement-breakpoint
DO $$ BEGIN
	IF NOT EXISTS (
		SELECT 1 FROM "pg_constraint" WHERE "conname" = 'model_department_overrides_reasoning_effort_check'
	) THEN
		ALTER TABLE "model_department_overrides" ADD CONSTRAINT "model_department_overrides_reasoning_effort_check" CHECK ("reasoning_effort" IS NULL OR "reasoning_effort" IN ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'));
	END IF;
END $$;
--> statement-breakpoint
DO $$ BEGIN
	IF NOT EXISTS (
		SELECT 1 FROM "pg_constraint" WHERE "conname" = 'model_profile_overrides_reasoning_effort_check'
	) THEN
		ALTER TABLE "model_profile_overrides" ADD CONSTRAINT "model_profile_overrides_reasoning_effort_check" CHECK ("reasoning_effort" IS NULL OR "reasoning_effort" IN ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'));
	END IF;
END $$;
