import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { ensureCodexSkillsInjected } from "@hermes-fabric/adapter-codex-local/server";

async function makeTempDir(prefix: string): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

async function createHermesFabricRepoSkill(root: string, skillName: string) {
  await fs.mkdir(path.join(root, "server"), { recursive: true });
  await fs.mkdir(path.join(root, "packages", "adapter-utils"), { recursive: true });
  await fs.mkdir(path.join(root, "skills", skillName), { recursive: true });
  await fs.writeFile(path.join(root, "pnpm-workspace.yaml"), "packages:\n  - packages/*\n", "utf8");
  await fs.writeFile(path.join(root, "package.json"), '{"name":"fabric"}\n', "utf8");
  await fs.writeFile(
    path.join(root, "skills", skillName, "SKILL.md"),
    `---\nname: ${skillName}\n---\n`,
    "utf8",
  );
}

async function createCustomSkill(root: string, skillName: string) {
  await fs.mkdir(path.join(root, "custom", skillName), { recursive: true });
  await fs.writeFile(
    path.join(root, "custom", skillName, "SKILL.md"),
    `---\nname: ${skillName}\n---\n`,
    "utf8",
  );
}

describe("codex local adapter skill injection", () => {
  const fabricKey = "hermes-fabric/fabric/fabric";
  const createAgentKey = "hermes-fabric/fabric/fabric-create-agent";
  const cleanupDirs = new Set<string>();

  afterEach(async () => {
    await Promise.all(Array.from(cleanupDirs).map((dir) => fs.rm(dir, { recursive: true, force: true })));
    cleanupDirs.clear();
  });

  it("repairs a Codex HermesFabric skill symlink that still points at another live checkout", async () => {
    const currentRepo = await makeTempDir("fabric-codex-current-");
    const oldRepo = await makeTempDir("fabric-codex-old-");
    const skillsHome = await makeTempDir("fabric-codex-home-");
    cleanupDirs.add(currentRepo);
    cleanupDirs.add(oldRepo);
    cleanupDirs.add(skillsHome);

    await createHermesFabricRepoSkill(currentRepo, "fabric");
    await createHermesFabricRepoSkill(currentRepo, "fabric-create-agent");
    await createHermesFabricRepoSkill(oldRepo, "fabric");
    await fs.symlink(path.join(oldRepo, "skills", "fabric"), path.join(skillsHome, "fabric"));

    const logs: Array<{ stream: "stdout" | "stderr"; chunk: string }> = [];
    await ensureCodexSkillsInjected(
      async (stream, chunk) => {
        logs.push({ stream, chunk });
      },
      {
        skillsHome,
        skillsEntries: [
          {
            key: fabricKey,
            runtimeName: "fabric",
            source: path.join(currentRepo, "skills", "fabric"),
          },
          {
            key: createAgentKey,
            runtimeName: "fabric-create-agent",
            source: path.join(currentRepo, "skills", "fabric-create-agent"),
          },
        ],
      },
    );

    expect(await fs.realpath(path.join(skillsHome, "fabric"))).toBe(
      await fs.realpath(path.join(currentRepo, "skills", "fabric")),
    );
    expect(await fs.realpath(path.join(skillsHome, "fabric-create-agent"))).toBe(
      await fs.realpath(path.join(currentRepo, "skills", "fabric-create-agent")),
    );
    expect(logs).toContainEqual(
      expect.objectContaining({
        stream: "stdout",
        chunk: expect.stringContaining('Repaired Codex skill "fabric"'),
      }),
    );
    expect(logs).toContainEqual(
      expect.objectContaining({
        stream: "stdout",
        chunk: expect.stringContaining('Injected Codex skill "fabric-create-agent"'),
      }),
    );
  });

  it("preserves a custom Codex skill symlink outside HermesFabric repo checkouts", async () => {
    const currentRepo = await makeTempDir("fabric-codex-current-");
    const customRoot = await makeTempDir("fabric-codex-custom-");
    const skillsHome = await makeTempDir("fabric-codex-home-");
    cleanupDirs.add(currentRepo);
    cleanupDirs.add(customRoot);
    cleanupDirs.add(skillsHome);

    await createHermesFabricRepoSkill(currentRepo, "fabric");
    await createCustomSkill(customRoot, "fabric");
    await fs.symlink(path.join(customRoot, "custom", "fabric"), path.join(skillsHome, "fabric"));

    await ensureCodexSkillsInjected(async () => {}, {
      skillsHome,
      skillsEntries: [{
        key: fabricKey,
        runtimeName: "fabric",
        source: path.join(currentRepo, "skills", "fabric"),
      }],
    });

    expect(await fs.realpath(path.join(skillsHome, "fabric"))).toBe(
      await fs.realpath(path.join(customRoot, "custom", "fabric")),
    );
  });

  it("prunes broken symlinks for unavailable HermesFabric repo skills before Codex starts", async () => {
    const currentRepo = await makeTempDir("fabric-codex-current-");
    const oldRepo = await makeTempDir("fabric-codex-old-");
    const skillsHome = await makeTempDir("fabric-codex-home-");
    cleanupDirs.add(currentRepo);
    cleanupDirs.add(oldRepo);
    cleanupDirs.add(skillsHome);

    await createHermesFabricRepoSkill(currentRepo, "fabric");
    await createHermesFabricRepoSkill(oldRepo, "agent-browser");
    const staleTarget = path.join(oldRepo, "skills", "agent-browser");
    await fs.symlink(staleTarget, path.join(skillsHome, "agent-browser"));
    await fs.rm(staleTarget, { recursive: true, force: true });

    const logs: Array<{ stream: "stdout" | "stderr"; chunk: string }> = [];
    await ensureCodexSkillsInjected(
      async (stream, chunk) => {
        logs.push({ stream, chunk });
      },
      {
        skillsHome,
        skillsEntries: [{
          key: fabricKey,
          runtimeName: "fabric",
          source: path.join(currentRepo, "skills", "fabric"),
        }],
      },
    );

    await expect(fs.lstat(path.join(skillsHome, "agent-browser"))).rejects.toMatchObject({
      code: "ENOENT",
    });
    expect(logs).toContainEqual(
      expect.objectContaining({
        stream: "stdout",
        chunk: expect.stringContaining('Removed stale Codex skill "agent-browser"'),
      }),
    );
  });

  it("preserves other live HermesFabric skill symlinks in the shared workspace skill directory", async () => {
    const currentRepo = await makeTempDir("fabric-codex-current-");
    const skillsHome = await makeTempDir("fabric-codex-home-");
    cleanupDirs.add(currentRepo);
    cleanupDirs.add(skillsHome);

    await createHermesFabricRepoSkill(currentRepo, "fabric");
    await createHermesFabricRepoSkill(currentRepo, "agent-browser");
    await fs.symlink(
      path.join(currentRepo, "skills", "agent-browser"),
      path.join(skillsHome, "agent-browser"),
    );

    await ensureCodexSkillsInjected(async () => {}, {
      skillsHome,
      skillsEntries: [{
        key: fabricKey,
        runtimeName: "fabric",
        source: path.join(currentRepo, "skills", "fabric"),
      }],
    });

    expect((await fs.lstat(path.join(skillsHome, "fabric"))).isSymbolicLink()).toBe(true);
    expect((await fs.lstat(path.join(skillsHome, "agent-browser"))).isSymbolicLink()).toBe(true);
    expect(await fs.realpath(path.join(skillsHome, "agent-browser"))).toBe(
      await fs.realpath(path.join(currentRepo, "skills", "agent-browser")),
    );
  });
});
