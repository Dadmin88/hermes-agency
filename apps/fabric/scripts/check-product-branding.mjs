#!/usr/bin/env node

import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const defaultRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const REQUIRED_CANONICAL_IDENTITY = [
  ["package.json", /"name"\s*:\s*"hermes-fabric"/],
  ["README.md", /Hermes Fabric/],
  ["HERMES_FABRIC.md", /Hermes Fabric/],
];

const LEGACY_RULES = [
  { rule: "legacy-package-scope", pattern: /@paperclipai\//i },
  { rule: "legacy-env-prefix", pattern: /\bPAPERCLIP_[A-Z0-9_]+\b/ },
  { rule: "legacy-config-path", pattern: /(?:~\/)?\.paperclip(?:\/|\b)/i },
  { rule: "legacy-cli-or-package-name", pattern: /\bpaperclipai\b|\bpaperclip[-/][a-z0-9._-]+/i },
  { rule: "legacy-product-name", pattern: /\bpaperclip\b/i },
];

const TEXT_EXTENSIONS = new Set([
  ".cjs",
  ".css",
  ".csv",
  ".env",
  ".example",
  ".go",
  ".html",
  ".js",
  ".json",
  ".jsx",
  ".lock",
  ".md",
  ".mjs",
  ".mts",
  ".py",
  ".rs",
  ".sh",
  ".sql",
  ".svg",
  ".toml",
  ".ts",
  ".tsx",
  ".txt",
  ".yaml",
  ".yml",
]);

const EXCLUDED_DIRECTORIES = new Set([
  ".git",
  ".next",
  ".turbo",
  "build",
  "coverage",
  "dist",
  "node_modules",
]);

const EXEMPT_EXACT_PATHS = new Set([
  "scripts/check-product-branding.mjs",
  "scripts/check-product-branding.test.mjs",
  "scripts/brand-allowlist.json",
  "scripts/brand-rules.mjs",
  "scripts/merge-upstream-snapshots.py",
  "scripts/normalize-upstream-import.py",
  "scripts/test-upstream-sync.py",
]);

function toPosix(filePath) {
  return filePath.split(path.sep).join("/");
}

function isTextFile(file) {
  const base = path.posix.basename(file);
  return (
    TEXT_EXTENSIONS.has(path.posix.extname(file)) ||
    base === "Dockerfile" ||
    base === "LICENSE" ||
    base === "NOTICE" ||
    base.includes(".env")
  );
}

function isTestOrFixture(file) {
  return (
    /(^|\/)(__tests__|tests|fixtures|storybook)(\/|$)/i.test(file) ||
    /\.(test|spec)\.[cm]?[jt]sx?$/i.test(file)
  );
}

function isExemptPath(file) {
  const normalized = toPosix(file);
  const base = path.posix.basename(normalized);

  if (EXEMPT_EXACT_PATHS.has(normalized)) return true;
  if (base === "LICENSE" || base === "NOTICE") return true;
  if (normalized.startsWith(".upstream/")) return true;
  if (normalized.includes("/migrations/")) return true;
  if (isTestOrFixture(normalized)) return true;
  if (
    normalized.startsWith("packages/teams-catalog/catalog/") &&
    normalized.endsWith("/.paperclip.yaml")
  ) {
    return true;
  }

  return false;
}

function isHistoricalDocumentationLine(file, line) {
  const normalized = toPosix(file).toLowerCase();
  const isDocumentation =
    normalized.endsWith(".md") ||
    normalized.startsWith("doc/") ||
    normalized.startsWith("docs/") ||
    normalized.includes("changelog") ||
    normalized.includes("release-notes") ||
    normalized.startsWith("releases/");

  if (!isDocumentation) return false;

  return /\b(upstream|legacy|historical|compatibility|migration|formerly|derived|fork|attribution|renamed|source project)\b/i.test(
    line,
  );
}

async function walkFiles(root) {
  const files = [];

  async function visit(directory) {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory() && EXCLUDED_DIRECTORIES.has(entry.name)) continue;
      const absolute = path.join(directory, entry.name);
      const relative = toPosix(path.relative(root, absolute));
      if (entry.isDirectory()) {
        await visit(absolute);
      } else if (entry.isFile() && isTextFile(relative)) {
        files.push(relative);
      }
    }
  }

  await visit(root);
  return files.sort();
}

async function listTrackedFiles(root) {
  try {
    const { stdout: topOutput } = await execFileAsync(
      "git",
      ["-C", root, "rev-parse", "--show-toplevel"],
      { encoding: "utf8" },
    );
    const top = topOutput.trim();
    const prefix = toPosix(path.relative(top, root));
    const args = ["-C", top, "ls-files", "-z"];
    if (prefix) args.push("--", prefix);
    const { stdout } = await execFileAsync("git", args, {
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
    });

    return stdout
      .split("\0")
      .filter(Boolean)
      .map((file) => {
        const normalized = toPosix(file);
        if (!prefix) return normalized;
        return normalized.startsWith(`${prefix}/`)
          ? normalized.slice(prefix.length + 1)
          : normalized;
      })
      .filter((file) => file && isTextFile(file))
      .sort();
  } catch {
    return walkFiles(root);
  }
}

async function verifyCanonicalIdentity(root) {
  const failures = [];
  for (const [file, pattern] of REQUIRED_CANONICAL_IDENTITY) {
    try {
      const content = await fs.readFile(path.join(root, file), "utf8");
      if (!pattern.test(content)) failures.push(file);
    } catch {
      failures.push(file);
    }
  }
  return failures;
}

function inspectContent(file, content) {
  const violations = [];
  const lines = content.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (isHistoricalDocumentationLine(file, line)) continue;

    for (const { rule, pattern } of LEGACY_RULES) {
      const match = pattern.exec(line);
      if (!match) continue;
      violations.push({
        kind: "content",
        rule,
        file,
        line: index + 1,
        column: (match.index ?? 0) + 1,
        text: line.trim(),
      });
      break;
    }
  }

  return violations;
}

export async function evaluateBranding({ root = defaultRoot } = {}) {
  const resolvedRoot = path.resolve(root);
  const canonicalIdentityFailures = await verifyCanonicalIdentity(resolvedRoot);
  const files = await listTrackedFiles(resolvedRoot);
  const violations = [];

  for (const file of files) {
    const normalized = toPosix(file);
    if (isExemptPath(normalized)) continue;

    if (/paperclip/i.test(normalized)) {
      violations.push({
        kind: "path",
        rule: "legacy-path-token",
        file: normalized,
        line: 0,
        column: 0,
        text: normalized,
      });
      continue;
    }

    const absolute = path.join(resolvedRoot, normalized);
    const content = await fs.readFile(absolute, "utf8").catch(() => null);
    if (content === null || content.includes("\u0000")) continue;
    violations.push(...inspectContent(normalized, content));
  }

  return {
    root: resolvedRoot,
    scannedFileCount: files.length,
    canonicalIdentityFailures,
    violations,
    violationCount: violations.length,
  };
}

function printResult(result) {
  if (result.canonicalIdentityFailures.length > 0) {
    console.error(
      `Canonical Hermes Fabric identity missing from: ${result.canonicalIdentityFailures.join(", ")}`,
    );
  }

  if (result.violationCount > 0) {
    console.error(
      `Found ${result.violationCount} forbidden inherited namespace reference(s):`,
    );
    for (const violation of result.violations.slice(0, 100)) {
      const location = violation.line > 0
        ? `${violation.file}:${violation.line}:${violation.column}`
        : violation.file;
      console.error(`  ${location} [${violation.rule}] ${violation.text}`);
    }
    if (result.violations.length > 100) {
      console.error(`  ... ${result.violations.length - 100} more`);
    }
  }

  if (
    result.canonicalIdentityFailures.length === 0 &&
    result.violationCount === 0
  ) {
    console.log(
      `Hermes Fabric canonical branding check passed (${result.scannedFileCount} tracked text files scanned)`,
    );
  }
}

async function main() {
  const result = await evaluateBranding();
  printResult(result);
  if (
    result.canonicalIdentityFailures.length > 0 ||
    result.violationCount > 0
  ) {
    process.exitCode = 1;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error));
    process.exitCode = 1;
  });
}
