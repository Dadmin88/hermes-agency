#!/usr/bin/env node
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const required = [
  ["package.json", /"name"\s*:\s*"hermes-fabric"/],
  ["README.md", /Hermes Fabric/],
  ["HERMES_FABRIC.md", /Hermes Fabric/],
];
for (const [file, pattern] of required) {
  const content = await fs.readFile(path.join(root, file), "utf8");
  if (!pattern.test(content)) throw new Error(`Canonical Hermes Fabric branding missing from ${file}`);
}
console.log("Hermes Fabric canonical branding check passed");
