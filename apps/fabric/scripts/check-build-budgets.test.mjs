import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { checkBuildBudgets } from "./check-build-budgets.mjs";

function fixture(jsBytes, cssBytes) {
  const root = mkdtempSync(path.join(tmpdir(), "fabric-build-budget-"));
  const assets = path.join(root, "assets");
  mkdirSync(assets);
  writeFileSync(path.join(assets, "index.js"), Buffer.alloc(jsBytes));
  writeFileSync(path.join(assets, "index.css"), Buffer.alloc(cssBytes));
  return assets;
}

test("accepts assets at or below their budgets", () => {
  const result = checkBuildBudgets({
    assetsDirectory: fixture(100, 50),
    budgets: { javascriptBytes: 100, cssBytes: 50 },
  });
  assert.deepEqual(result.violations, []);
});

test("reports JavaScript and CSS budget violations", () => {
  const result = checkBuildBudgets({
    assetsDirectory: fixture(101, 51),
    budgets: { javascriptBytes: 100, cssBytes: 50 },
  });
  assert.equal(result.violations.length, 2);
  assert.match(result.violations[0], /JavaScript budget is 100/);
  assert.match(result.violations[1], /CSS budget is 50/);
});
