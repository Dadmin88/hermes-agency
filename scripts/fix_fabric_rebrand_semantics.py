#!/usr/bin/env python3
"""Repair semantic contracts after the one-time Fabric namespace migration.

The bulk migration intentionally handles names and paths mechanically. This
second pass fixes identifiers whose meaning is not branding, including icons,
catalog keys, SQL namespaces, environment precedence, and assertions.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FABRIC = ROOT / "apps" / "fabric"


def replace(path: Path, old: str, new: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if old in text:
        path.write_text(text.replace(old, new), encoding="utf-8")


def regex_replace(path: Path, pattern: str, replacement: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count:
        path.write_text(updated, encoding="utf-8")


def repair_attachment_icons() -> None:
    ui_root = FABRIC / "ui"
    repaired: list[Path] = []
    for path in ui_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "lucide-react" not in text or "HermesFabric" not in text:
            continue
        path.write_text(text.replace("HermesFabric", "Link2"), encoding="utf-8")
        repaired.append(path)

    remaining = []
    for path in ui_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "lucide-react" in text and "HermesFabric" in text:
            remaining.append(path.relative_to(FABRIC).as_posix())
    if remaining:
        raise RuntimeError(f"unrepaired attachment icon imports: {remaining}")
    print(f"Repaired {len(repaired)} attachment icon source files")


def repair_ui_contracts() -> None:
    pricing = FABRIC / "ui/src/pages/ModelPricing.tsx"
    replace(pricing, "description: `${result.discovered} models discovered`", "body: `${result.discovered} models discovered`")
    replace(pricing, "description: error.message", "body: error.message")


def repair_catalog_identifiers() -> None:
    roots = [
        FABRIC / "packages/teams-catalog",
        FABRIC / "packages/skills-catalog",
        FABRIC / "skills",
    ]
    replacements = [
        ("Hermes Fabricai/", "hermes-fabric/"),
        ("HermesFabricai/", "hermes-fabric/"),
        ("Hermes Fabric-operations", "fabric-operations"),
        ("HermesFabric-operations", "fabric-operations"),
        ("Hermes Fabricai", "hermes-fabric"),
        ("HermesFabricai", "hermes-fabric"),
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".ts", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            updated = text
            for old, new in replacements:
                updated = updated.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def repair_environment_contract() -> None:
    env_module = FABRIC / "server/src/fabric-env.ts"
    env_module.write_text(
        '''/**
 * Hermes Fabric environment variable layer.
 *
 * HERMES_FABRIC_<name> is canonical. FABRIC_<name> remains a read-only
 * compatibility alias for installations created during the earlier rename.
 * Writes publish only the canonical key so child processes receive one
 * unambiguous value.
 */

export function fabricEnv(name: string): string | undefined {
  return process.env[`HERMES_FABRIC_${name}`] ?? process.env[`FABRIC_${name}`];
}

export function fabricEnvSet(name: string, value: string): void {
  process.env[`HERMES_FABRIC_${name}`] = value;
}

export function fabricEnvDefined(name: string): boolean {
  return (
    process.env[`HERMES_FABRIC_${name}`] !== undefined ||
    process.env[`FABRIC_${name}`] !== undefined
  );
}
''',
        encoding="utf-8",
    )

    loader = FABRIC / "server/src/services/plugin-loader.ts"
    regex_replace(
        loader,
        r'''const env: Record<string, string> = \{\s*FABRIC_DEPLOYMENT_MODE: input\.instanceInfo\.deploymentMode \?\? "",\s*HERMES_FABRIC_DEPLOYMENT_MODE: input\.instanceInfo\.deploymentMode \?\? "",\s*FABRIC_DEPLOYMENT_EXPOSURE: input\.instanceInfo\.deploymentExposure \?\? "",\s*HERMES_FABRIC_DEPLOYMENT_EXPOSURE: input\.instanceInfo\.deploymentExposure \?\? "",\s*\};''',
        '''const env: Record<string, string> = {
    HERMES_FABRIC_DEPLOYMENT_MODE: input.instanceInfo.deploymentMode ?? "",
    HERMES_FABRIC_DEPLOYMENT_EXPOSURE: input.instanceInfo.deploymentExposure ?? "",
  };''',
    )


def repair_plugin_namespaces() -> None:
    migration_root = FABRIC / "packages/plugins/plugin-llm-wiki/migrations"
    if migration_root.exists():
        for path in migration_root.glob("*.sql"):
            replace(path, "plugin_llm_wiki_8f50da974f", "plugin_llm_wiki_1584484592")

    test_path = FABRIC / "server/src/__tests__/plugin-database.test.ts"
    replace(test_path, '"FABRIC_DEPLOYMENT_MODE": "authenticated",\n', "")
    replace(test_path, '"FABRIC_DEPLOYMENT_EXPOSURE": "public",\n', "")


def repair_test_language() -> None:
    secrets_test = FABRIC / "server/src/__tests__/secrets-service.test.ts"
    replace(secrets_test, "HermesFabric-managed namespace", "Hermes Agency-managed namespace")

    skill_test = FABRIC / "server/src/__tests__/fabric-skill-utils.test.ts"
    regex_replace(
        skill_test,
        r'''\s*it\("keeps the create-issue-interaction-ui guide as a maintainer-only skill", async \(\) => \{.*?\n\s*\}\);''',
        '''
  it("does not expose the maintainer interaction guide as a runtime skill", async () => {
    await expect(
      fs.access(path.resolve("skills/create-issue-interaction-ui/SKILL.md")),
    ).rejects.toThrow();
  });''',
    )


def main() -> None:
    repair_attachment_icons()
    repair_ui_contracts()
    repair_catalog_identifiers()
    repair_environment_contract()
    repair_plugin_namespaces()
    repair_test_language()
    print("Repaired Hermes Fabric semantic contracts after namespace migration")


if __name__ == "__main__":
    main()
