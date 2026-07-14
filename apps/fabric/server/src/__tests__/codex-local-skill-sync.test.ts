import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  listCodexSkills,
  syncCodexSkills,
} from "@hermes-fabric/adapter-codex-local/server";

async function makeTempDir(prefix: string): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

describe("codex local skill sync", () => {
  const fabricKey = "hermes-fabric/fabric/fabric";
  const cleanupDirs = new Set<string>();

  afterEach(async () => {
    await Promise.all(Array.from(cleanupDirs).map((dir) => fs.rm(dir, { recursive: true, force: true })));
    cleanupDirs.clear();
  });

  it("reports configured HermesFabric skills for workspace injection on the next run", async () => {
    const codexHome = await makeTempDir("fabric-codex-skill-sync-");
    cleanupDirs.add(codexHome);

    const ctx = {
      agentId: "agent-1",
      companyId: "company-1",
      adapterType: "codex_local",
      config: {
        env: {
          CODEX_HOME: codexHome,
        },
        fabricSkillSync: {
          desiredSkills: [fabricKey],
        },
      },
    } as const;

    const before = await listCodexSkills(ctx);
    expect(before.mode).toBe("ephemeral");
    expect(before.desiredSkills).toContain(fabricKey);
    expect(before.entries.find((entry) => entry.key === fabricKey)?.state).toBe("configured");
    expect(before.entries.find((entry) => entry.key === fabricKey)?.detail).toContain("CODEX_HOME/skills/");
  });

  it("does not persist HermesFabric skills into CODEX_HOME during sync", async () => {
    const codexHome = await makeTempDir("fabric-codex-skill-prune-");
    cleanupDirs.add(codexHome);

    const configuredCtx = {
      agentId: "agent-2",
      companyId: "company-1",
      adapterType: "codex_local",
      config: {
        env: {
          CODEX_HOME: codexHome,
        },
        fabricSkillSync: {
          desiredSkills: [fabricKey],
        },
      },
    } as const;

    const after = await syncCodexSkills(configuredCtx, [fabricKey]);
    expect(after.mode).toBe("ephemeral");
    expect(after.entries.find((entry) => entry.key === fabricKey)?.state).toBe("configured");
    await expect(fs.lstat(path.join(codexHome, "skills", "fabric"))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("normalizes legacy flat HermesFabric skill refs before reporting configured state", async () => {
    const codexHome = await makeTempDir("fabric-codex-legacy-skill-sync-");
    cleanupDirs.add(codexHome);

    const snapshot = await listCodexSkills({
      agentId: "agent-3",
      companyId: "company-1",
      adapterType: "codex_local",
      config: {
        env: {
          CODEX_HOME: codexHome,
        },
        fabricSkillSync: {
          desiredSkills: ["fabric"],
        },
      },
    });

    expect(snapshot.warnings).toEqual([]);
    expect(snapshot.desiredSkills).toContain(fabricKey);
    expect(snapshot.desiredSkills).not.toContain("fabric");
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.state).toBe("configured");
    expect(snapshot.entries.find((entry) => entry.key === "fabric")).toBeUndefined();
  });
});
