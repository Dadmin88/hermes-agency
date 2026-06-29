#!/usr/bin/env node
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { getRepoRootFromScript, matchFingerprint, scanBrandMatches, summarizeMatches } from "./brand-rules.mjs";

const DEFAULT_PROTECTED_CATEGORIES = ["ui", "server", "docs"];
const DEFAULT_ALLOWLIST_PATH = "scripts/brand-allowlist.json";

function parseArgs(argv) {
  const args = { reportOnly: false, json: false, updateReport: false, updateAllowlist: false, root: null, allowlist: null, scope: null, help: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--report-only") args.reportOnly = true;
    else if (arg === "--json") args.json = true;
    else if (arg === "--update-report") args.updateReport = true;
    else if (arg === "--update-allowlist") args.updateAllowlist = true;
    else if (arg === "--root") args.root = argv[++index];
    else if (arg === "--allowlist") args.allowlist = argv[++index];
    else if (arg === "--scope") args.scope = argv[++index];
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function printHelp() {
  console.log(`Usage: node scripts/check-product-branding.mjs [options]\n\nFails on unallowlisted user-facing Paperclip/Hermes Fabric references.\n\nOptions:\n  --report-only       Print violations but exit 0.\n  --json              Print JSON report.\n  --update-report     Write scripts/brand-inventory-report.json.\n  --update-allowlist  Replace baseline fingerprints in the allowlist with current protected-category matches.\n  --scope <name>      Restrict check to a category or top-level path prefix, e.g. ui, server, docs.\n  --root <path>       Scan a different root (used by tests).\n  --allowlist <path>  Use a different allowlist JSON file.`);
}

function makeDefaultAllowlist() {
  return {
    schemaVersion: 1,
    description: "Branding guardrail allowlist. Category policies permit compatibility/legal/internal references. Baseline fingerprints temporarily permit existing user-facing references until staged rebrand PRs remove them.",
    allowedCategories: ["package-internal", "env-config-compat", "legal-upstream", "historical", "tests"],
    allowedPathPrefixes: [],
    allowedLinePatterns: [
      "@paperclipai/",
      "paperclipai",
      "PAPERCLIP_",
      "HERMES_FABRIC",
      "~/.paperclip",
      ".paperclip",
      "paperclip-",
      "paperclip/",
      "postgres://paperclip",
      "upstream",
      "MIT License"
    ],
    protectedCategories: DEFAULT_PROTECTED_CATEGORIES,
    baselineFingerprints: []
  };
}

async function readAllowlist(allowlistPath) {
  try {
    return JSON.parse(await fs.readFile(allowlistPath, "utf8"));
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    return makeDefaultAllowlist();
  }
}

function isScoped(match, scope) {
  if (!scope) return true;
  if (match.category === scope) return true;
  const normalized = scope.replace(/\/$/, "");
  return match.file === normalized || match.file.startsWith(`${normalized}/`);
}

function isAllowedByPolicy(match, allowlist) {
  if ((allowlist.allowedCategories ?? []).includes(match.category)) return true;
  if ((allowlist.allowedPathPrefixes ?? []).some((prefix) => match.file.startsWith(prefix))) return true;
  if ((allowlist.allowedLinePatterns ?? []).some((pattern) => match.text.includes(pattern))) return true;
  return false;
}

function findViolations(protectedMatches, allowlist) {
  const baselineFingerprints = new Set(allowlist.baselineFingerprints ?? []);
  return protectedMatches.filter((match) => !isAllowedByPolicy(match, allowlist) && !baselineFingerprints.has(matchFingerprint(match)));
}

export async function evaluateBranding({ root, allowlistPath, scope = null } = {}) {
  const scanRoot = root ? path.resolve(root) : getRepoRootFromScript(import.meta.url);
  const resolvedAllowlistPath = allowlistPath ? path.resolve(allowlistPath) : path.join(scanRoot, DEFAULT_ALLOWLIST_PATH);
  const allowlist = await readAllowlist(resolvedAllowlistPath);
  const protectedCategories = new Set(allowlist.protectedCategories ?? DEFAULT_PROTECTED_CATEGORIES);
  const matches = (await scanBrandMatches(scanRoot)).filter((match) => isScoped(match, scope));
  const protectedMatches = matches.filter((match) => protectedCategories.has(match.category));
  const violations = findViolations(protectedMatches, allowlist);
  return {
    root: scanRoot,
    allowlistPath: resolvedAllowlistPath,
    scope,
    summary: summarizeMatches(matches),
    protectedCount: protectedMatches.length,
    violationCount: violations.length,
    violations,
    matches,
    protectedMatches,
    allowlist
  };
}

function allowlistWithCurrentBaseline(result) {
  const fingerprints = [];
  for (const match of result.protectedMatches) {
    if (!isAllowedByPolicy(match, result.allowlist)) fingerprints.push(matchFingerprint(match));
  }
  return {
    ...result.allowlist,
    updatedAt: new Date().toISOString(),
    baselineFingerprints: [...new Set(fingerprints)].sort()
  };
}

function printHumanReport(result) {
  console.log("Hermes Agency product branding check");
  console.log(`Root: ${result.root}`);
  if (result.scope) console.log(`Scope: ${result.scope}`);
  console.log(`Matches: ${result.summary.totalMatches} across ${result.summary.totalFiles} files`);
  console.log(`Protected-category matches: ${result.protectedCount}`);
  console.log(`Violations: ${result.violationCount}`);
  if (result.violationCount > 0) {
    console.log("\nUnallowlisted user-facing branding references:");
    for (const violation of result.violations.slice(0, 50)) {
      console.log(`  ${violation.file}:${violation.line}:${violation.column} [${violation.category}] ${violation.term} — ${violation.text}`);
    }
    if (result.violations.length > 50) console.log(`  ... ${result.violations.length - 50} more`);
  } else {
    console.log("No unallowlisted user-facing Paperclip/Hermes Fabric references found.");
  }
}

async function maybeWriteReport(result) {
  const reportPath = path.join(result.root, "scripts", "brand-inventory-report.json");
  const report = {
    generatedAt: new Date().toISOString(),
    root: result.root,
    summary: result.summary,
    violations: result.violations,
    matches: result.matches
  };
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }
  const root = args.root ? path.resolve(args.root) : getRepoRootFromScript(import.meta.url);
  const allowlistPath = args.allowlist ? path.resolve(args.allowlist) : path.join(root, DEFAULT_ALLOWLIST_PATH);
  const result = await evaluateBranding({ root, allowlistPath, scope: args.scope });
  if (args.updateAllowlist) {
    result.allowlist = allowlistWithCurrentBaseline(result);
    await fs.writeFile(allowlistPath, `${JSON.stringify(result.allowlist, null, 2)}\n`);
    result.violations = [];
    result.violationCount = 0;
  }
  if (args.updateReport) await maybeWriteReport(result);
  if (args.json) {
    console.log(JSON.stringify({ root: result.root, allowlistPath: result.allowlistPath, scope: result.scope, summary: result.summary, protectedCount: result.protectedCount, violationCount: result.violationCount, violations: result.violations }, null, 2));
  } else {
    printHumanReport(result);
  }
  if (result.violationCount > 0 && !args.reportOnly) process.exitCode = 1;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error));
    process.exitCode = 1;
  });
}
