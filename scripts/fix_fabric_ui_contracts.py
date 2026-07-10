#!/usr/bin/env python3
"""Finalize Hermes Fabric public UI copy and rebrand-sensitive test contracts."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps" / "fabric" / "ui" / "src"


def replace(path: Path, old: str, new: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    updated = text.replace(old, new)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def replace_product_copy(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    updated = text.replace("HermesFabric", "Hermes Fabric")
    updated = updated.replace("Hermes Agency", "Hermes Fabric")
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def repair_public_product_surfaces() -> None:
    for relative in (
        "components/BootstrapPendingPage.tsx",
        "components/SidebarAccountMenu.tsx",
        "pages/CloudUpstream.tsx",
        "pages/InviteLanding.tsx",
        "pages/Secrets.tsx",
        "pages/secrets/ImportFromVaultDialog.tsx",
    ):
        replace_product_copy(UI / relative)

    cloud = UI / "pages/CloudUpstream.tsx"
    replace(cloud, 'aria-label="Hermes Fabric cloud stack URL"', 'aria-label="Hermes Fabric Cloud stack URL"')

    import_dialog = UI / "pages/secrets/ImportFromVaultDialog.tsx"
    replace(import_dialog, "A Hermes Fabric secret already uses this name.", "A Fabric secret already uses this name.")
    replace(import_dialog, "A Hermes Fabric secret already uses this key.", "A Fabric secret already uses this key.")


def repair_renamed_fixtures() -> None:
    fixture_files = (
        "components/MarkdownBody.test.tsx",
        "components/MarkdownEditor.test.tsx",
        "components/SearchableSelect.test.tsx",
        "pages/CompanyAccess.test.tsx",
        "pages/CloudUpstream.test.tsx",
        "pages/InviteLanding.test.tsx",
        "pages/Secrets.render.test.tsx",
        "pages/secrets/ImportFromVaultDialog.test.tsx",
        "lib/reusable-execution-workspaces.test.ts",
    )
    for relative in fixture_files:
        replace(UI / relative, "HermesFabric", "Hermes Fabric")

    editor = UI / "components/MarkdownEditor.test.tsx"
    replace(editor, 'value="@Pap"', 'value="@Her"')
    replace(editor, '"@Pap".length', '"@Her".length')

    searchable = UI / "components/SearchableSelect.test.tsx"
    replace(searchable, 'setInputValue(input!, "pclip reusable")', 'setInputValue(input!, "fabric reusable")')

    reusable = UI / "lib/reusable-execution-workspaces.test.ts"
    replace(reusable, 'reusableWorkspaceOptionMatches(option, "pclip reusable")', 'reusableWorkspaceOptionMatches(option, "fabric reusable")')

    agents = UI / "pages/Agents.test.tsx"
    replace(agents, 'container.querySelector(".w-56")', 'container.querySelector(".sm\\:w-56")')


def repair_legacy_catalog_aliases() -> None:
    path = UI / "pages/CompanySkills.tsx"
    text = path.read_text(encoding="utf-8")
    anchor = "  const lower = trimmed.toLowerCase();\n"
    addition = '''  const migratedPrefix = "fabric";\n  if (lower === `${migratedPrefix} bundled`) return "Hermes Agency bundled";\n  if (lower === `${migratedPrefix} workspace`) return "Hermes Agency workspace";\n  if (lower === `${migratedPrefix}-board`) return "Hermes Agency dashboard";\n  if (lower === `${migratedPrefix}-capsules`) return "Hermes Agency capsules";\n  if (lower.startsWith(`${migratedPrefix}-`)) {\n    const suffix = trimmed.slice(`${migratedPrefix}-`.length).replace(/[-_]+/g, " ");\n    return `Hermes Agency ${suffix}`;\n  }\n'''
    if addition not in text:
        if anchor not in text:
            raise RuntimeError("CompanySkills legacy label anchor missing")
        path.write_text(text.replace(anchor, anchor + addition, 1), encoding="utf-8")


def repair_roster_tests() -> None:
    path = UI / "pages/HermesAgencyRoster.test.tsx"
    text = path.read_text(encoding="utf-8")

    old_error = '''    expect(container.textContent).toContain("agency-backend-engineer");\n    expect(container.textContent).toContain("Offline target");\n    expect(container.textContent).toContain("Error: profile agency-backend-engineer not found");'''
    new_error = '''    expect(container.textContent).toContain("agency-backend-engineer");\n    expect(container.textContent).toContain("Offline target");\n    const backendRow = Array.from(container.querySelectorAll("button")).find((button) =>\n      button.textContent?.includes("agency-backend-engineer"),\n    ) as HTMLButtonElement | undefined;\n    expect(backendRow).toBeTruthy();\n    await act(async () => {\n      backendRow?.click();\n    });\n    await flushReact();\n    expect(container.textContent).toContain("Error: profile agency-backend-engineer not found");'''
    if old_error in text:
        text = text.replace(old_error, new_error, 1)

    old_dispatch = '''    await act(async () => {\n      (container.querySelector("button") as HTMLButtonElement).click();\n    });\n    await flushReact();\n\n    expect(mockHermesAgencyApi.dispatch).toHaveBeenCalledWith(expect.objectContaining({'''
    new_dispatch = '''    const agentRow = Array.from(container.querySelectorAll("button")).find((button) =>\n      button.textContent?.includes("agency-backend-engineer"),\n    ) as HTMLButtonElement | undefined;\n    const taskControls = Array.from(container.querySelectorAll("button")).find((button) =>\n      button.textContent?.trim() === "Task controls",\n    ) as HTMLButtonElement | undefined;\n    expect(agentRow).toBeTruthy();\n    expect(taskControls).toBeTruthy();\n    await act(async () => {\n      agentRow?.click();\n      taskControls?.click();\n    });\n    await flushReact();\n    const sendTask = Array.from(container.querySelectorAll("button")).find((button) =>\n      button.textContent?.includes("Send task"),\n    ) as HTMLButtonElement | undefined;\n    expect(sendTask).toBeTruthy();\n    await act(async () => {\n      sendTask?.click();\n    });\n    await flushReact();\n\n    expect(mockHermesAgencyApi.dispatch).toHaveBeenCalledWith(expect.objectContaining({'''
    if old_dispatch in text:
        text = text.replace(old_dispatch, new_dispatch, 1)

    path.write_text(text, encoding="utf-8")


def main() -> None:
    repair_public_product_surfaces()
    repair_renamed_fixtures()
    repair_legacy_catalog_aliases()
    repair_roster_tests()
    print("Finalized Hermes Fabric UI and rebrand-sensitive test contracts")


if __name__ == "__main__":
    main()
