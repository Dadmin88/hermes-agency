import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const BRAND_TERMS = ["Hermes Fabric", "HERMES_FABRIC", "PAPERCLIP", "Paperclip", "paperclip"];

export const DEFAULT_EXCLUDED_DIRS = new Set([
  ".git",
  "node_modules",
  "dist",
  "build",
  "coverage",
  "storybook-static",
  "playwright-report",
  "test-results",
  ".turbo",
  ".next",
  "__pycache__",
]);

export const DEFAULT_EXCLUDED_FILES = new Set([
  "scripts/brand-rules.mjs",
  "scripts/brand-inventory.mjs",
  "scripts/check-product-branding.mjs",
  "scripts/check-product-branding.test.mjs",
  "scripts/brand-allowlist.json",
  "scripts/brand-inventory-report.json",
]);

const TEXT_EXTENSIONS = new Set([
  ".cjs",
  ".css",
  ".csv",
  ".env",
  ".example",
  ".html",
  ".js",
  ".json",
  ".jsx",
  ".lock",
  ".md",
  ".mjs",
  ".mts",
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

export function toPosixPath(filePath) {
  return filePath.split(path.sep).join("/");
}

export function normalizeLine(line) {
  return line.trim().replace(/\s+/g, " ");
}

export function lineHash(line) {
  return createHash("sha256").update(normalizeLine(line)).digest("hex").slice(0, 16);
}

export function matchFingerprint(match) {
  return `${match.file}::${match.term}::${match.lineHash}`;
}

export function isProbablyTextFile(filePath) {
  const ext = path.extname(filePath);
  const base = path.basename(filePath);
  return TEXT_EXTENSIONS.has(ext) || base.includes(".env") || base === "Dockerfile" || base === "LICENSE";
}

export async function walkFiles(rootDir, options = {}) {
  const excludedDirs = new Set(options.excludedDirs ?? DEFAULT_EXCLUDED_DIRS);
  const excludedFiles = new Set(options.excludedFiles ?? DEFAULT_EXCLUDED_FILES);
  const files = [];

  async function visit(dir) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory() && excludedDirs.has(entry.name)) continue;
      const absolutePath = path.join(dir, entry.name);
      const relativePath = toPosixPath(path.relative(rootDir, absolutePath));
      if (entry.isDirectory()) {
        await visit(absolutePath);
      } else if (entry.isFile() && isProbablyTextFile(relativePath) && !excludedFiles.has(relativePath)) {
        files.push({ absolutePath, relativePath });
      }
    }
  }

  await visit(rootDir);
  return files.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
}

export function categorizeMatch(file, line) {
  const lowerFile = file.toLowerCase();
  const lowerLine = line.toLowerCase();

  if (lowerFile.includes("license") || lowerFile.includes("notice") || lowerLine.includes("mit license") || lowerLine.includes("upstream")) {
    return "legal-upstream";
  }

  if (lowerFile.startsWith("releases/") || lowerFile.includes("changelog") || lowerFile.includes("release-notes")) {
    return "historical";
  }

  if (
    lowerLine.includes("paperclip_") ||
    lowerLine.includes("hermes_fabric") ||
    lowerLine.includes("~/.paperclip") ||
    lowerLine.includes(".paperclip") ||
    lowerLine.includes("paperclipai") ||
    lowerLine.includes("paperclip-") ||
    lowerLine.includes("paperclip/") ||
    lowerLine.includes("paperclip:") ||
    lowerLine.includes("paperclip=") ||
    lowerLine.includes("postgres://paperclip")
  ) {
    return "env-config-compat";
  }

  if (
    lowerFile.endsWith("package.json") ||
    lowerFile.endsWith("pnpm-lock.yaml") ||
    lowerFile.endsWith("tsconfig.json") ||
    lowerFile.startsWith("packages/") ||
    lowerLine.includes("@paperclipai/") ||
    lowerLine.includes("from \\\"") ||
    lowerLine.includes("from '") ||
    lowerLine.includes("import(")
  ) {
    return "package-internal";
  }

  if (lowerFile.includes("/__tests__/") || lowerFile.includes("/tests/") || /(^|[./-])(test|spec)\.[cm]?[jt]sx?$/.test(lowerFile)) {
    return "tests";
  }

  if (lowerFile.startsWith("ui/") || lowerFile.includes("/stories/") || lowerFile.includes(".stories.")) return "ui";
  if (lowerFile.startsWith("server/")) return "server";
  if (lowerFile.startsWith("doc/") || lowerFile.startsWith("docs/") || lowerFile.endsWith(".md")) return "docs";

  return "package-internal";
}

export async function scanBrandMatches(rootDir, options = {}) {
  const files = await walkFiles(rootDir, options);
  const matches = [];

  for (const { absolutePath, relativePath } of files) {
    const content = await fs.readFile(absolutePath, "utf8").catch(() => null);
    if (content === null || content.includes("\u0000")) continue;
    const lines = content.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      for (const term of BRAND_TERMS) {
        let start = line.indexOf(term);
        while (start !== -1) {
          const match = {
            file: relativePath,
            line: index + 1,
            column: start + 1,
            term,
            text: line.trim(),
            lineHash: lineHash(line),
            category: categorizeMatch(relativePath, line),
          };
          match.fingerprint = matchFingerprint(match);
          matches.push(match);
          start = line.indexOf(term, start + term.length);
        }
      }
    }
  }

  return matches;
}

export function summarizeMatches(matches) {
  const byTerm = Object.create(null);
  const byCategory = Object.create(null);
  const byFile = Object.create(null);
  const byCategoryTerm = Object.create(null);

  for (const match of matches) {
    byTerm[match.term] = (byTerm[match.term] ?? 0) + 1;
    byCategory[match.category] = (byCategory[match.category] ?? 0) + 1;
    byFile[match.file] = (byFile[match.file] ?? 0) + 1;
    const key = `${match.category}:${match.term}`;
    byCategoryTerm[key] = (byCategoryTerm[key] ?? 0) + 1;
  }

  const topFiles = Object.entries(byFile)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 25)
    .map(([file, count]) => ({ file, count }));

  return {
    totalMatches: matches.length,
    totalFiles: Object.keys(byFile).length,
    byTerm,
    byCategory,
    byCategoryTerm,
    topFiles,
  };
}

export function getRepoRootFromScript(scriptUrl) {
  return path.resolve(path.dirname(fileURLToPath(scriptUrl)), "..");
}
