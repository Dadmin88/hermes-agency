import { promises as fs } from "node:fs";
import path from "node:path";

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

const EXCLUDED_DIRS = new Set([
  ".git",
  "node_modules",
  "dist",
  "build",
  "coverage",
  ".cache",
  ".next",
  ".turbo",
  "__pycache__",
]);

const SCANNER_FILES = new Set([
  "scripts/brand-allowlist.json",
  "scripts/brand-rules.mjs",
  "scripts/check-product-branding.mjs",
  "scripts/check-product-branding.test.mjs",
]);

export function toPosixPath(filePath) {
  return filePath.split(path.sep).join("/");
}

function isTextFile(filePath) {
  const base = path.basename(filePath);
  const extension = path.extname(filePath).toLowerCase();
  return (
    TEXT_EXTENSIONS.has(extension) ||
    base.includes(".env") ||
    base === "Dockerfile" ||
    base === "LICENSE" ||
    base === "NOTICE"
  );
}

export function categorizePath(file) {
  const normalized = toPosixPath(file);
  const lower = normalized.toLowerCase();
  const base = path.posix.basename(lower);

  if (SCANNER_FILES.has(normalized)) return "scanner";
  if (
    base === "license" ||
    base.startsWith("license.") ||
    base === "notice" ||
    base.startsWith("notice.")
  ) {
    return "legal";
  }
  if (
    lower === "changelog.md" ||
    lower.includes("/changelog") ||
    lower.includes("/releases/") ||
    lower.includes("release-notes")
  ) {
    return "historical";
  }
  if (lower.startsWith(".upstream/conflicts/")) return "upstream-conflict";
  if (
    lower.includes("/__tests__/") ||
    lower.startsWith("tests/") ||
    lower.includes("/tests/") ||
    lower.includes("/fixtures/") ||
    /(^|[./-])(test|spec)\.[cm]?[jt]sx?$/.test(lower)
  ) {
    return "tests";
  }
  return "protected";
}

export async function walkTextFiles(rootDir) {
  const files = [];

  async function visit(directory) {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory() && EXCLUDED_DIRS.has(entry.name)) continue;
      const absolutePath = path.join(directory, entry.name);
      const relativePath = toPosixPath(path.relative(rootDir, absolutePath));
      if (entry.isDirectory()) {
        await visit(absolutePath);
      } else if (entry.isFile() && isTextFile(relativePath)) {
        files.push({ absolutePath, relativePath });
      }
    }
  }

  await visit(rootDir);
  return files.sort((left, right) => left.relativePath.localeCompare(right.relativePath));
}

function classifyContentMatch(line, start) {
  const tail = line.slice(start);
  if (/^@paperclipai\//i.test(tail)) return "package-scope";
  if (/^PAPERCLIP_[A-Z0-9_]*/.test(tail)) return "env-prefix";
  if (/^(?:~\/|\/)?\.paperclip(?:\/|\b)/i.test(tail)) return "runtime-path";
  if (/^paperclipai\b/i.test(tail)) return "package-name";
  return "product-name";
}

export async function scanLegacyBranding(rootDir) {
  const files = await walkTextFiles(rootDir);
  const matches = [];

  for (const { absolutePath, relativePath } of files) {
    const category = categorizePath(relativePath);
    const lowerPath = relativePath.toLowerCase();
    const pathIndex = lowerPath.indexOf("paperclip");
    if (pathIndex !== -1) {
      matches.push({
        source: "path",
        kind: "legacy-filename",
        file: relativePath,
        line: 0,
        column: pathIndex + 1,
        text: relativePath,
        category,
      });
    }

    const content = await fs.readFile(absolutePath, "utf8").catch(() => null);
    if (content === null || content.includes("\u0000")) continue;

    const lines = content.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const regex = /paperclip/giu;
      for (const match of line.matchAll(regex)) {
        const start = match.index ?? 0;
        matches.push({
          source: "content",
          kind: classifyContentMatch(line, start),
          file: relativePath,
          line: index + 1,
          column: start + 1,
          text: line.trim(),
          category,
        });
      }
    }
  }

  return matches;
}

export function summarizeMatches(matches) {
  const byKind = Object.create(null);
  const byCategory = Object.create(null);
  for (const match of matches) {
    byKind[match.kind] = (byKind[match.kind] ?? 0) + 1;
    byCategory[match.category] = (byCategory[match.category] ?? 0) + 1;
  }
  return {
    totalMatches: matches.length,
    totalFiles: new Set(matches.map((match) => match.file)).size,
    byKind,
    byCategory,
  };
}
