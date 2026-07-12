import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { evaluateBranding } from "./check-product-branding.mjs";

async function makeFixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), "hermes-fabric-branding-"));
  await writeFile(path.join(root, "package.json"), '{"name":"hermes-fabric"}\n');
  await writeFile(path.join(root, "README.md"), "# Hermes Fabric\n");
  await writeFile(path.join(root, "HERMES_FABRIC.md"), "# Hermes Fabric\n");
  return root;
}

async function writeFixture(root, relativePath, content) {
  const target = path.join(root, relativePath);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, content);
}

test("rejects a legacy runtime product name", async () => {
  const root = await makeFixture();
  await writeFixture(root, "server/src/runtime.ts", 'export const productName = "Paperclip";\n');

  const result = await evaluateBranding({ root });

  assert.equal(result.violationCount, 1);
  assert.equal(result.violations[0].kind, "content");
  assert.equal(result.violations[0].rule, "legacy-product-name");
});

test("rejects a legacy package scope", async () => {
  const root = await makeFixture();
  await writeFixture(root, "packages/example/package.json", '{"name":"@paperclipai/example"}\n');

  const result = await evaluateBranding({ root });

  assert.equal(result.violationCount, 1);
  assert.equal(result.violations[0].rule, "legacy-package-scope");
});

test("rejects a legacy environment prefix", async () => {
  const root = await makeFixture();
  await writeFixture(root, "server/src/config.ts", 'const value = process.env.PAPERCLIP_DATABASE_URL;\n');

  const result = await evaluateBranding({ root });

  assert.equal(result.violationCount, 1);
  assert.equal(result.violations[0].rule, "legacy-env-prefix");
});

test("rejects a legacy filename", async () => {
  const root = await makeFixture();
  await writeFixture(root, "skills/paperclip-board/SKILL.md", "# Board skill\n");

  const result = await evaluateBranding({ root });

  assert.equal(result.violationCount, 1);
  assert.equal(result.violations[0].kind, "path");
  assert.equal(result.violations[0].rule, "legacy-path-token");
});

test("allows legal attribution and explicit upstream normalization fixtures", async () => {
  const root = await makeFixture();
  await writeFixture(root, "NOTICE", "Derived from Paperclip under the MIT License.\n");
  await writeFixture(
    root,
    "scripts/normalize-upstream-import.py",
    'LEGACY_ALIASES = ["Paperclip", "@paperclipai/"]\n',
  );
  await writeFixture(
    root,
    "docs/history.md",
    "The legacy Paperclip name is retained here for historical attribution.\n",
  );

  const result = await evaluateBranding({ root });

  assert.equal(result.violationCount, 0);
});
