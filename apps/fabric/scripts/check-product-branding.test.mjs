import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { scanBrandMatches } from "./brand-rules.mjs";
import { evaluateBranding } from "./check-product-branding.mjs";

async function makeFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "brand-check-"));
  await mkdir(path.join(root, "ui", "src"), { recursive: true });
  await mkdir(path.join(root, "packages", "example"), { recursive: true });
  const allowlistPath = path.join(root, "brand-allowlist.json");
  await writeFile(
    allowlistPath,
    JSON.stringify(
      {
        schemaVersion: 1,
        allowedCategories: ["package-internal", "env-config-compat", "legal-upstream", "historical", "tests"],
        allowedPathPrefixes: [],
        allowedLinePatterns: [],
        protectedCategories: ["ui", "server", "docs"],
        baselineFingerprints: []
      },
      null,
      2
    )
  );
  return { root, allowlistPath };
}

test("flags unallowlisted user-facing legacy product names", async () => {
  const { root, allowlistPath } = await makeFixture();
  await writeFile(path.join(root, "ui", "src", "App.tsx"), "export const title = 'Welcome to Paperclip';\n");

  const result = await evaluateBranding({ root, allowlistPath });

  assert.equal(result.violationCount, 1);
  assert.equal(result.violations[0].file, "ui/src/App.tsx");
  assert.equal(result.violations[0].term, "Paperclip");
});

test("allows internal package compatibility references", async () => {
  const { root, allowlistPath } = await makeFixture();
  await writeFile(path.join(root, "packages", "example", "package.json"), '{"name":"@paperclipai/example"}\n');

  const result = await evaluateBranding({ root, allowlistPath });

  assert.equal(result.violationCount, 0);
});

test("honors baseline fingerprints for staged cleanup", async () => {
  const { root, allowlistPath } = await makeFixture();
  const filePath = path.join(root, "ui", "src", "Skills.tsx");
  await writeFile(filePath, "export const label = 'Paperclip bundled';\n");
  const [match] = await scanBrandMatches(root);
  assert.ok(match?.fingerprint);
  await writeFile(
    allowlistPath,
    JSON.stringify(
      {
        schemaVersion: 1,
        allowedCategories: ["package-internal", "env-config-compat", "legal-upstream", "historical", "tests"],
        allowedPathPrefixes: [],
        allowedLinePatterns: [],
        protectedCategories: ["ui", "server", "docs"],
        baselineFingerprints: [match.fingerprint]
      },
      null,
      2
    )
  );

  const result = await evaluateBranding({ root, allowlistPath });

  assert.equal(result.violationCount, 0);
});
