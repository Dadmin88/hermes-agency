#!/usr/bin/env node
import { promises as fs } from "node:fs";
import path from "node:path";
import { BRAND_TERMS, DEFAULT_EXCLUDED_DIRS, getRepoRootFromScript, scanBrandMatches, summarizeMatches } from "./brand-rules.mjs";

function parseArgs(argv) {
  const args = { json: false, updateReport: false, help: false };
  for (const arg of argv) {
    if (arg === "--json") args.json = true;
    else if (arg === "--update-report") args.updateReport = true;
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/brand-inventory.mjs [--json] [--update-report]\n\nScans apps/fabric for legacy product-brand references, excluding generated/heavy directories.\n\nOptions:\n  --json           Print machine-readable JSON only.\n  --update-report  Write scripts/brand-inventory-report.json.`);
}

function printHumanReport(report) {
  console.log("Hermes Agency branding inventory");
  console.log(`Root: ${report.root}`);
  console.log(`Matches: ${report.summary.totalMatches} across ${report.summary.totalFiles} files`);

  console.log("\nBy term:");
  for (const [term, count] of Object.entries(report.summary.byTerm).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    console.log(`  ${term}: ${count}`);
  }

  console.log("\nBy category:");
  for (const [category, count] of Object.entries(report.summary.byCategory).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    console.log(`  ${category}: ${count}`);
  }

  console.log("\nBy category + term:");
  for (const [key, count] of Object.entries(report.summary.byCategoryTerm).sort((a, b) => a[0].localeCompare(b[0]))) {
    console.log(`  ${key}: ${count}`);
  }

  console.log("\nTop files:");
  for (const item of report.summary.topFiles) {
    console.log(`  ${item.count.toString().padStart(5, " ")}  ${item.file}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const root = getRepoRootFromScript(import.meta.url);
  const matches = await scanBrandMatches(root);
  const report = {
    generatedAt: new Date().toISOString(),
    root,
    terms: BRAND_TERMS,
    excludedDirs: [...DEFAULT_EXCLUDED_DIRS],
    summary: summarizeMatches(matches),
    matches,
  };

  if (args.updateReport) {
    await fs.writeFile(path.join(root, "scripts", "brand-inventory-report.json"), `${JSON.stringify(report, null, 2)}\n`);
  }

  if (args.json) console.log(JSON.stringify(report, null, 2));
  else printHumanReport(report);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
