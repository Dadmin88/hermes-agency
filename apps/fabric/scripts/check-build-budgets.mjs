#!/usr/bin/env node
import { readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_BUDGETS = Object.freeze({
  javascriptBytes: 5_250_000,
  cssBytes: 400_000,
});

function largestFile(directory, suffix) {
  const candidates = readdirSync(directory)
    .filter((name) => name.endsWith(suffix))
    .map((name) => ({ name, bytes: statSync(path.join(directory, name)).size }))
    .sort((left, right) => right.bytes - left.bytes);
  if (candidates.length === 0) {
    throw new Error(`No ${suffix} assets found in ${directory}`);
  }
  return candidates[0];
}

export function checkBuildBudgets({ assetsDirectory, budgets = DEFAULT_BUDGETS }) {
  const javascript = largestFile(assetsDirectory, ".js");
  const css = largestFile(assetsDirectory, ".css");
  const violations = [];
  if (javascript.bytes > budgets.javascriptBytes) {
    violations.push(
      `${javascript.name} is ${javascript.bytes} bytes; JavaScript budget is ${budgets.javascriptBytes}`,
    );
  }
  if (css.bytes > budgets.cssBytes) {
    violations.push(`${css.name} is ${css.bytes} bytes; CSS budget is ${budgets.cssBytes}`);
  }
  return { javascript, css, budgets, violations };
}

function main() {
  const assetsDirectory = path.resolve(process.argv[2] ?? "ui/dist/assets");
  const result = checkBuildBudgets({ assetsDirectory });
  console.log(
    `[build-budget] largest JavaScript: ${result.javascript.name} (${result.javascript.bytes} bytes)`,
  );
  console.log(`[build-budget] largest CSS: ${result.css.name} (${result.css.bytes} bytes)`);
  if (result.violations.length > 0) {
    for (const violation of result.violations) console.error(`[build-budget] ${violation}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main();
}
