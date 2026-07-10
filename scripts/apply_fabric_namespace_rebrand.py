#!/usr/bin/env python3
"""Remove the inherited Paperclip namespace from Hermes Fabric.

The migration updates tracked text, package scopes, runtime/config identifiers,
URLs, commands, and tracked filenames. It is deliberately deterministic and
idempotent so CI can apply it on a disposable branch and verify the result.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FABRIC = ROOT / "apps" / "fabric"

PROSE_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
TEXT_SUFFIXES = {
    ".cjs", ".css", ".csv", ".env", ".example", ".go", ".html", ".js",
    ".json", ".jsx", ".lock", ".md", ".mdx", ".mjs", ".mts", ".py",
    ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt",
    ".yaml", ".yml",
}
TEXT_BASENAMES = {
    "Dockerfile", "LICENSE", "NOTICE", "Makefile", "Procfile", "AGENTS.md",
}

URL_REPLACEMENTS = [
    ("https://github.com/paperclipai/paperclip", "https://github.com/DeployFaith/Hermes_Agency"),
    ("http://github.com/paperclipai/paperclip", "https://github.com/DeployFaith/Hermes_Agency"),
    ("github.com/paperclipai/paperclip", "github.com/DeployFaith/Hermes_Agency"),
    ("https://github.com/paperclipai", "https://github.com/DeployFaith"),
    ("github.com/paperclipai", "github.com/DeployFaith"),
    ("https://paperclipai.com", "https://www.deployfaith.xyz/agency"),
    ("paperclipai.com", "deployfaith.xyz/agency"),
]

TECHNICAL_REPLACEMENTS = [
    ("@paperclipai/", "@hermes-fabric/"),
    ("@paperclipai", "@hermes-fabric"),
    ("PAPERCLIP_AI", "HERMES_FABRIC"),
    ("PAPERCLIPAI", "HERMES_FABRIC"),
    ("PAPERCLIP_", "HERMES_FABRIC_"),
    ("PAPERCLIP", "HERMES_FABRIC"),
    ("PaperclipAI", "HermesFabric"),
    ("PaperclipAi", "HermesFabric"),
    ("paperclipAI", "hermesFabric"),
    ("paperclipai", "hermes-fabric"),
    ("Paperclip", "HermesFabric"),
    ("paperclip", "fabric"),
]

PROSE_REPLACEMENTS = [
    ("Paperclip AI", "Hermes Fabric"),
    ("PaperclipAI", "Hermes Fabric"),
    ("Paperclip", "Hermes Fabric"),
    ("paperclip", "Hermes Fabric"),
    ("PAPERCLIP", "HERMES FABRIC"),
]

PATH_REPLACEMENTS = [
    ("PaperclipAI", "HermesFabric"),
    ("Paperclip", "HermesFabric"),
    ("PAPERCLIP", "HERMES_FABRIC"),
    ("paperclipai", "hermes-fabric"),
    ("paperclip", "fabric"),
]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, check=check, capture_output=True)


def tracked_paths() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item.decode() for item in raw.split(b"\0") if item]


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_BASENAMES or ".env" in path.name


def apply_common(value: str) -> str:
    for old, new in URL_REPLACEMENTS:
        value = value.replace(old, new)
    # Avoid producing a duplicate hermes-fabric script key in the root package.
    value = value.replace('"paperclipai": "node cli/', '"fabric": "node cli/')
    value = value.replace('"metrics:paperclip-commits"', '"metrics:fabric-commits"')
    value = value.replace("~/.paperclip", "~/.hermes-fabric")
    value = value.replace(".paperclip.yaml", ".fabric.yaml")
    value = value.replace(".paperclip.yml", ".fabric.yml")
    return value


def replace_technical(value: str) -> str:
    value = apply_common(value)
    for old, new in TECHNICAL_REPLACEMENTS:
        value = value.replace(old, new)
    return value


def replace_inline_markdown(line: str) -> str:
    # Inline-code spans are technical; surrounding prose uses the public product name.
    parts = line.split("`")
    for index, part in enumerate(parts):
        if index % 2:
            parts[index] = replace_technical(part)
        else:
            prose = apply_common(part)
            for old, new in PROSE_REPLACEMENTS:
                prose = prose.replace(old, new)
            parts[index] = prose
    return "`".join(parts)


def replace_markdown(value: str) -> str:
    lines: list[str] = []
    fenced = False
    for line in value.splitlines(keepends=True):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            lines.append(replace_technical(line))
            fenced = not fenced
            continue
        lines.append(replace_technical(line) if fenced else replace_inline_markdown(line))
    return "".join(lines)


def polish_code_strings(value: str) -> str:
    # Preserve identifiers such as HermesFabricPlugin while making exact product-name
    # occurrences inside strings and JSX text human-readable.
    string_pattern = re.compile(r"(?P<q>['\"`])(?P<body>(?:\\.|(?!\1).)*?)(?P=q)", re.S)

    def polish(match: re.Match[str]) -> str:
        body = re.sub(r"(?<![A-Za-z0-9_])HermesFabric(?![A-Za-z0-9_])", "Hermes Fabric", match.group("body"))
        return f"{match.group('q')}{body}{match.group('q')}"

    value = string_pattern.sub(polish, value)
    value = re.sub(
        r">([^<]*)<",
        lambda match: ">" + re.sub(r"\bHermesFabric\b", "Hermes Fabric", match.group(1)) + "<",
        value,
    )
    return value


def migrate_content(path: Path) -> None:
    if not path.exists() or not path.is_file() or not is_text(path):
        return
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if "\x00" in original:
        return
    if path.suffix.lower() in PROSE_SUFFIXES:
        updated = replace_markdown(original)
    else:
        updated = polish_code_strings(replace_technical(original))
    # Correct canonical product relations after generic replacement.
    updated = updated.replace("Hermes Fabric Agency", "Hermes Agency")
    updated = updated.replace("HermesFabric Agency", "Hermes Agency")
    updated = updated.replace("Hermes Fabric agents", "Hermes Agency agents")
    updated = updated.replace("Hermes Fabric roster", "Hermes Agency roster")
    updated = updated.replace("Hermes Fabric team", "Hermes Agency team")
    updated = updated.replace("Hermes Fabric execution substrate", "Hermes Agency execution substrate")
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def renamed_component(name: str) -> str:
    result = name
    for old, new in PATH_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def rename_tracked_paths() -> None:
    candidates = [
        path for path in tracked_paths()
        if re.search(r"paperclip", str(path.relative_to(ROOT)), re.I)
    ]
    # Move files first. Git infers directory renames from the file moves and this
    # avoids merge/collision ambiguity for nested legacy directories.
    for source in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        if not source.exists() or not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        target_relative = Path(*(renamed_component(part) for part in relative.parts))
        if target_relative == relative:
            continue
        target = ROOT / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError(f"rebrand path collision: {relative} -> {target_relative}")
        run("git", "mv", str(relative), str(target_relative))


def rewrite_brand_guard() -> None:
    scripts = FABRIC / "scripts"
    checker = scripts / "check-product-branding.mjs"
    checker.write_text(
        '''#!/usr/bin/env node\nimport { promises as fs } from "node:fs";\nimport path from "node:path";\nimport { fileURLToPath } from "node:url";\n\nconst root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");\nconst required = [\n  ["package.json", /"name"\\s*:\\s*"hermes-fabric"/],\n  ["README.md", /Hermes Fabric/],\n  ["HERMES_FABRIC.md", /Hermes Fabric/],\n];\nfor (const [file, pattern] of required) {\n  const content = await fs.readFile(path.join(root, file), "utf8");\n  if (!pattern.test(content)) throw new Error(`Canonical Hermes Fabric branding missing from ${file}`);\n}\nconsole.log("Hermes Fabric canonical branding check passed");\n''',
        encoding="utf-8",
    )
    for relative in [
        "brand-rules.mjs",
        "brand-inventory.mjs",
        "check-product-branding.test.mjs",
        "brand-allowlist.json",
        "brand-inventory-report.json",
    ]:
        target = scripts / relative
        if target.exists():
            run("git", "rm", str(target.relative_to(ROOT)))


def normalize_root_package() -> None:
    package_path = FABRIC / "package.json"
    package = json.loads(package_path.read_text())
    scripts = package.setdefault("scripts", {})
    scripts.pop("paperclipai", None)
    scripts["fabric"] = "node cli/node_modules/tsx/dist/cli.mjs cli/src/index.ts"
    if "metrics:paperclip-commits" in scripts:
        scripts["metrics:fabric-commits"] = scripts.pop("metrics:paperclip-commits")
    scripts["metrics:fabric-commits"] = scripts.get(
        "metrics:fabric-commits", "tsx scripts/fabric-commit-metrics.ts"
    ).replace("paperclip", "fabric")
    package_path.write_text(json.dumps(package, indent=2) + "\n")


def assert_clean() -> None:
    content_hits: list[str] = []
    path_hits: list[str] = []
    for path in tracked_paths():
        relative = str(path.relative_to(ROOT))
        if re.search("paperclip", relative, re.I):
            path_hits.append(relative)
        if path.exists() and path.is_file() and is_text(path):
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if re.search("paperclip", content, re.I):
                content_hits.append(relative)
    if path_hits or content_hits:
        raise RuntimeError(
            "legacy brand remains\npaths:\n"
            + "\n".join(path_hits[:100])
            + "\ncontent:\n"
            + "\n".join(content_hits[:100])
        )


def main() -> None:
    for path in tracked_paths():
        migrate_content(path)
    rename_tracked_paths()
    # Re-run content migration after path moves so renamed files and generated path
    # references are normalized under their final locations.
    for path in tracked_paths():
        migrate_content(path)
    rewrite_brand_guard()
    normalize_root_package()
    assert_clean()
    print("Hermes Fabric namespace migration applied with zero legacy-brand tokens")


if __name__ == "__main__":
    main()
