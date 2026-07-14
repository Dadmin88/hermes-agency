#!/usr/bin/env python3
"""Normalize an upstream Fabric snapshot into Hermes Fabric namespaces.

The legacy source identity is provided through environment variables so this
repository never needs to hardcode inherited product names.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

TEXT_SUFFIXES = {
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
    ".mdx",
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
    ".hcl",
    ".mod",
    ".webmanifest",
    ".jsonc",
    ".yaml",
    ".yml",
}
TEXT_BASENAMES = {
    "Dockerfile",
    "LICENSE",
    "NOTICE",
    "Makefile",
    "Procfile",
    ".gitignore",
    ".dockerignore",
}
PROSE_SUFFIXES = {".md", ".mdx", ".rst", ".txt"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".turbo", ".next"}


def aliases_from_env() -> list[str]:
    raw = os.environ.get("FABRIC_UPSTREAM_LEGACY_ALIASES", "")
    aliases = [item.strip() for item in raw.split(",") if item.strip()]
    if not aliases:
        raise SystemExit("FABRIC_UPSTREAM_LEGACY_ALIASES is required")
    return sorted(set(aliases), key=len, reverse=True)


def package_scopes_from_env() -> list[str]:
    raw = os.environ.get("FABRIC_UPSTREAM_LEGACY_SCOPES", "")
    return sorted({item.strip() for item in raw.split(",") if item.strip()}, key=len, reverse=True)


def is_text(path: Path) -> bool:
    return (
        path.suffix.lower() in TEXT_SUFFIXES
        or path.name in TEXT_BASENAMES
        or path.name.startswith("Dockerfile")
        or not path.suffix
        or ".env" in path.name
    )


def walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            continue
        if path.is_file() and is_text(path):
            files.append(path)
    return sorted(files)


def alias_variants(alias: str) -> list[tuple[str, str, str]]:
    compact = re.sub(r"[^A-Za-z0-9]", "", alias)
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|\d+", compact) or [compact]
    pascal = "".join(word[:1].upper() + word[1:].lower() for word in words)
    camel = pascal[:1].lower() + pascal[1:] if pascal else compact
    kebab = "-".join(word.lower() for word in words)
    snake = "_".join(word.lower() for word in words)
    upper_snake = snake.upper()
    variants = {
        alias,
        alias.lower(),
        alias.upper(),
        compact,
        compact.lower(),
        compact.upper(),
        pascal,
        camel,
        kebab,
        snake,
        upper_snake,
    }
    result: list[tuple[str, str, str]] = []
    for value in sorted((item for item in variants if item), key=len, reverse=True):
        if value.isupper():
            result.append((value, "HERMES_FABRIC", "HERMES FABRIC"))
        elif "-" in value:
            result.append((value, "hermes-fabric", "Hermes Fabric"))
        elif "_" in value:
            result.append((value, "hermes_fabric", "Hermes Fabric"))
        elif value[:1].isupper():
            result.append((value, "Hermes Fabric", "Hermes Fabric"))
        else:
            result.append((value, "hermesFabric", "Hermes Fabric"))
    return result


def replacement_table(aliases: list[str]) -> list[tuple[str, str, str]]:
    table: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for alias in aliases:
        for old, technical, prose in alias_variants(alias):
            if old not in seen:
                table.append((old, technical, prose))
                seen.add(old)
    return sorted(table, key=lambda item: len(item[0]), reverse=True)


def replace_technical(value: str, table: list[tuple[str, str, str]], scopes: list[str]) -> str:
    for scope in scopes:
        value = value.replace(f"{scope}/", "@hermes-fabric/")
        value = value.replace(scope, "@hermes-fabric")
    for old, technical, _ in table:
        value = value.replace(old, technical)
    value = value.replace("Hermes Agency", "Hermes Agency")
    value = value.replace("HermesFabric roster", "Hermes Agency roster")
    value = value.replace("HermesFabric team", "Hermes Agency team")
    return value


def replace_markdown(value: str, table: list[tuple[str, str, str]], scopes: list[str]) -> str:
    lines: list[str] = []
    fenced = False
    for line in value.splitlines(keepends=True):
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            lines.append(replace_technical(line, table, scopes))
            fenced = not fenced
            continue
        if fenced:
            lines.append(replace_technical(line, table, scopes))
            continue
        parts = line.split("`")
        for index, part in enumerate(parts):
            if index % 2:
                parts[index] = replace_technical(part, table, scopes)
            else:
                for scope in scopes:
                    part = part.replace(scope, "Hermes Fabric")
                for old, _, prose in table:
                    part = part.replace(old, prose)
                part = part.replace("Hermes Agency", "Hermes Agency")
                part = part.replace("Hermes Agency roster", "Hermes Agency roster")
                part = part.replace("Hermes Agency team", "Hermes Agency team")
                parts[index] = part
        lines.append("`".join(parts))
    return "".join(lines)


def rename_component(name: str, table: list[tuple[str, str, str]]) -> str:
    result = name
    for old, technical, _ in table:
        result = result.replace(old, technical)
    return result


def rename_paths(root: Path, table: list[tuple[str, str, str]]) -> None:
    candidates = [
        path
        for path in root.rglob("*")
        if not any(part in SKIP_DIRS for part in path.relative_to(root).parts)
        and any(old in path.name for old, _, _ in table)
    ]
    for source in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        if not source.exists() and not source.is_symlink():
            continue
        target = source.with_name(rename_component(source.name, table))
        if target == source:
            continue
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"normalization path collision: {source} -> {target}")
        source.rename(target)


def normalize(root: Path, aliases: list[str], scopes: list[str]) -> None:
    table = replacement_table(aliases)
    for path in walk_files(root):
        if path.name in {"LICENSE", "NOTICE"}:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "\x00" in original:
            continue
        updated = (
            replace_markdown(original, table, scopes)
            if path.suffix.lower() in PROSE_SUFFIXES
            else replace_technical(original, table, scopes)
        )
        if updated != original:
            path.write_text(updated, encoding="utf-8")
    rename_paths(root, table)
    # Renaming directories can expose final paths that need one last content pass.
    for path in walk_files(root):
        if path.name in {"LICENSE", "NOTICE"}:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = (
            replace_markdown(original, table, scopes)
            if path.suffix.lower() in PROSE_SUFFIXES
            else replace_technical(original, table, scopes)
        )
        if updated != original:
            path.write_text(updated, encoding="utf-8")


def assert_clean(root: Path, aliases: list[str], scopes: list[str]) -> None:
    needles = [*aliases, *scopes]
    path_hits: list[str] = []
    content_hits: list[str] = []
    lowered = [needle.lower() for needle in needles if needle]
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        relative = str(path.relative_to(root))
        if any(needle in relative.lower() for needle in lowered):
            path_hits.append(relative)
        if path.is_symlink() or not path.is_file() or not is_text(path):
            continue
        if path.name in {"LICENSE", "NOTICE"}:
            continue
        try:
            content = path.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        if any(needle in content for needle in lowered):
            content_hits.append(relative)
    if path_hits or content_hits:
        raise RuntimeError(
            "upstream normalization incomplete\npaths:\n"
            + "\n".join(path_hits[:100])
            + "\ncontent:\n"
            + "\n".join(content_hits[:100])
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    aliases = aliases_from_env()
    scopes = package_scopes_from_env()
    normalize(root, aliases, scopes)
    assert_clean(root, aliases, scopes)
    print(f"Normalized upstream snapshot at {root}")


if __name__ == "__main__":
    main()
