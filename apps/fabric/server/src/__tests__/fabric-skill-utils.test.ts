import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  listHermesFabricSkillEntries,
  removeMaintainerOnlySkillSymlinks,
} from "@hermes-fabric/adapter-utils/server-utils";

async function makeTempDir(prefix: string): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

describe("fabric skill utils", () => {
  const cleanupDirs = new Set<string>();

  afterEach(async () => {
    await Promise.all(Array.from(cleanupDirs).map((dir) => fs.rm(dir, { recursive: true, force: true })));
    cleanupDirs.clear();
  });

  it("lists bundled runtime skills from ./skills without pulling in .agents/skills", async () => {
    const root = await makeTempDir("fabric-skill-roots-");
    cleanupDirs.add(root);

    const moduleDir = path.join(root, "a", "b", "c", "d", "e");
    await fs.mkdir(moduleDir, { recursive: true });
    await fs.mkdir(path.join(root, "skills", "fabric"), { recursive: true });
    await fs.mkdir(path.join(root, "skills", "fabric-create-agent"), { recursive: true });
    await fs.mkdir(path.join(root, ".agents", "skills", "diagnose-why-work-stopped"), { recursive: true });
    await fs.mkdir(path.join(root, ".agents", "skills", "fabric-create-plugin"), { recursive: true });
    await fs.mkdir(path.join(root, ".agents", "skills", "release"), { recursive: true });
    await fs.mkdir(path.join(root, ".agents", "skills", "terminal-bench-loop"), { recursive: true });

    const entries = await listHermesFabricSkillEntries(moduleDir);

    expect(entries.map((entry) => entry.key)).toEqual([
      "hermes-fabric/fabric/fabric",
      "hermes-fabric/fabric/fabric-create-agent",
    ]);
    expect(entries.map((entry) => entry.runtimeName)).toEqual([
      "fabric",
      "fabric-create-agent",
    ]);
    expect(entries[0]?.source).toBe(path.join(root, "skills", "fabric"));
    expect(entries[1]?.source).toBe(path.join(root, "skills", "fabric-create-agent"));
  });

  it("documents artifact uploads in the installed HermesFabric skill", async () => {
    const skillBody = await fs.readFile(path.resolve("skills/fabric/SKILL.md"), "utf8");
    const referenceBody = await fs.readFile(path.resolve("skills/fabric/references/artifacts.md"), "utf8");

    expect(skillBody).toContain("Generated Artifacts and Work Products");
    expect(skillBody).toContain("references/artifacts.md");
    expect(skillBody).not.toContain("/api/companies/$HERMES_FABRIC_COMPANY_ID/issues/$HERMES_FABRIC_TASK_ID/attachments");
    expect(referenceBody).toContain("Generated Artifacts and Work Products");
    expect(referenceBody).toContain("scripts/fabric-upload-artifact.sh");
    expect(referenceBody).toContain("POST");
    expect(referenceBody).toContain("/api/companies/$HERMES_FABRIC_COMPANY_ID/issues/$HERMES_FABRIC_TASK_ID/attachments");
    expect(referenceBody).toContain("/api/issues/$HERMES_FABRIC_TASK_ID/work-products");
    await expect(
      fs.access(path.resolve("skills/fabric/scripts/fabric-upload-artifact.sh")),
    ).resolves.toBeUndefined();
    await expect(fs.access(path.resolve("scripts/fabric-upload-artifact.sh"))).rejects.toThrow();
  });
  it("does not expose the maintainer interaction guide as a runtime skill", async () => {
    await expect(
      fs.access(path.resolve("skills/create-issue-interaction-ui/SKILL.md")),
    ).rejects.toThrow();
  });

  it("removes stale maintainer-only symlinks from a shared skills home", async () => {
    const root = await makeTempDir("fabric-skill-cleanup-");
    cleanupDirs.add(root);

    const skillsHome = path.join(root, "skills-home");
    const runtimeSkill = path.join(root, "skills", "fabric");
    const customSkill = path.join(root, "custom", "release-notes");
    const staleMaintainerSkill = path.join(root, ".agents", "skills", "release");

    await fs.mkdir(skillsHome, { recursive: true });
    await fs.mkdir(runtimeSkill, { recursive: true });
    await fs.mkdir(customSkill, { recursive: true });

    await fs.symlink(runtimeSkill, path.join(skillsHome, "fabric"));
    await fs.symlink(customSkill, path.join(skillsHome, "release-notes"));
    await fs.symlink(staleMaintainerSkill, path.join(skillsHome, "release"));

    const removed = await removeMaintainerOnlySkillSymlinks(skillsHome, ["fabric"]);

    expect(removed).toEqual(["release"]);
    await expect(fs.lstat(path.join(skillsHome, "release"))).rejects.toThrow();
    expect((await fs.lstat(path.join(skillsHome, "fabric"))).isSymbolicLink()).toBe(true);
    expect((await fs.lstat(path.join(skillsHome, "release-notes"))).isSymbolicLink()).toBe(true);
  });
});
