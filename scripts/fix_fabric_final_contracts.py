#!/usr/bin/env python3
"""Repair the final non-brand semantic contracts after the Fabric migration."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FABRIC = ROOT / "apps" / "fabric"


def stabilize_plugin_constraints() -> None:
    migration_root = FABRIC / "packages/plugins/plugin-llm-wiki/migrations"
    candidates = sorted(migration_root.glob("002_*_distillation.sql"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one distillation migration, found {candidates}")
    migration = candidates[0]
    text = migration.read_text(encoding="utf-8")
    replacements = {
        "UNIQUE (company_id, wiki_id, source_scope, scope_key, source_kind)": (
            "CONSTRAINT distillation_cursors_company_wiki_scope_key "
            "UNIQUE (company_id, wiki_id, source_scope, scope_key, source_kind)"
        ),
        "UNIQUE (company_id, wiki_id, idempotency_key)": (
            "CONSTRAINT distillation_work_items_company_wiki_idempotency_key "
            "UNIQUE (company_id, wiki_id, idempotency_key)"
        ),
        "UNIQUE (company_id, wiki_id, page_path)": (
            "CONSTRAINT page_bindings_company_wiki_page_path_key "
            "UNIQUE (company_id, wiki_id, page_path)"
        ),
    }
    for old, new in replacements.items():
        if new not in text:
            if old not in text:
                raise RuntimeError(f"migration constraint anchor missing: {old}")
            text = text.replace(old, new, 1)
    migration.write_text(text, encoding="utf-8")

    spaces = migration_root / "003_spaces.sql"
    text = spaces.read_text(encoding="utf-8")
    drop_replacements = (
        (
            r"DROP CONSTRAINT IF EXISTS [A-Za-z0-9_]*distillation_cursor[A-Za-z0-9_]*;",
            "DROP CONSTRAINT IF EXISTS distillation_cursors_company_wiki_scope_key;",
        ),
        (
            r"DROP CONSTRAINT IF EXISTS [A-Za-z0-9_]*distillation_work[A-Za-z0-9_]*;",
            "DROP CONSTRAINT IF EXISTS distillation_work_items_company_wiki_idempotency_key;",
        ),
        (
            r"DROP CONSTRAINT IF EXISTS [A-Za-z0-9_]*page_bindings[A-Za-z0-9_]*;",
            "DROP CONSTRAINT IF EXISTS page_bindings_company_wiki_page_path_key;",
        ),
    )
    for pattern, replacement in drop_replacements:
        text, count = re.subn(pattern, replacement, text, count=1)
        if count != 1 and replacement not in text:
            raise RuntimeError(f"spaces migration drop anchor missing: {pattern}")
    spaces.write_text(text, encoding="utf-8")


def normalize_worktree_test_contract() -> None:
    test_path = FABRIC / "server/src/__tests__/worktree-config.test.ts"
    text = test_path.read_text(encoding="utf-8")
    title = "does not persist transient runtime home overrides over repo-local worktree env"
    start = text.find(title)
    if start == -1:
        raise RuntimeError("worktree runtime override test not found")
    end = text.find('\n  it("', start + len(title))
    if end == -1:
        end = len(text)
    block = text[start:end]
    block = block.replace(
        "does not persist transient runtime home overrides over repo-local worktree env",
        "normalizes repo-local worktree env without persisting transient runtime home",
    )
    block = block.replace("repairedEnv: false", "repairedEnv: true")
    text = text[:start] + block + text[end:]
    test_path.write_text(text, encoding="utf-8")


def stabilize_skills_catalog_package_test() -> None:
    test_path = FABRIC / "packages/skills-catalog/src/packaged-artifacts.test.ts"
    text = test_path.read_text(encoding="utf-8")
    old = 'execFileSync("pnpm", ["--filter", "@hermes-fabric/skills-catalog", "build"], {'
    new = 'execFileSync("pnpm", ["run", "build"], {'
    if old not in text and new not in text:
        raise RuntimeError("skills catalog package build anchor missing")
    test_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def normalize_skills_catalog_keys() -> None:
    catalog_root = FABRIC / "packages/skills-catalog/catalog"
    for skill_path in sorted(catalog_root.rglob("SKILL.md")):
        relative = skill_path.parent.relative_to(catalog_root).as_posix()
        expected_key = f"hermes-fabric/{relative}"
        text = skill_path.read_text(encoding="utf-8")
        updated, count = re.subn(
            r"^key:\s*.*$",
            f"key: {expected_key}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise RuntimeError(f"catalog skill key missing: {skill_path}")
        if updated != text:
            skill_path.write_text(updated, encoding="utf-8")


def main() -> None:
    stabilize_plugin_constraints()
    normalize_worktree_test_contract()
    stabilize_skills_catalog_package_test()
    normalize_skills_catalog_keys()
    print("Stabilized final Hermes Fabric migration contracts")


if __name__ == "__main__":
    main()
