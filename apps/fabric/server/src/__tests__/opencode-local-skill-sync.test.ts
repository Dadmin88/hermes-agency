import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  listOpenCodeSkills,
  syncOpenCodeSkills,
} from "@hermes-fabric/adapter-opencode-local/server";

async function makeTempDir(prefix: string): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

describe("opencode local skill sync", () => {
  const fabricKey = "hermes-fabric/fabric/fabric";
  const cleanupDirs = new Set<string>();

  afterEach(async () => {
    await Promise.all(Array.from(cleanupDirs).map((dir) => fs.rm(dir, { recursive: true, force: true })));
    cleanupDirs.clear();
  });

  it("reports configured HermesFabric skills and installs them into the shared Claude/OpenCode skills home", async () => {
    const home = await makeTempDir("fabric-opencode-skill-sync-");
    cleanupDirs.add(home);

    const ctx = {
      agentId: "agent-1",
      companyId: "company-1",
      adapterType: "opencode_local",
      config: {
        env: {
          HOME: home,
        },
        fabricSkillSync: {
          desiredSkills: [fabricKey],
        },
      },
    } as const;

    const before = await listOpenCodeSkills(ctx);
    expect(before.mode).toBe("persistent");
    expect(before.warnings).toContain("OpenCode currently uses the shared Claude skills home (~/.claude/skills).");
    expect(before.desiredSkills).toContain(fabricKey);
    expect(before.entries.find((entry) => entry.key === fabricKey)?.state).toBe("missing");

    const after = await syncOpenCodeSkills(ctx, [fabricKey]);
    expect(after.entries.find((entry) => entry.key === fabricKey)?.state).toBe("installed");
    expect((await fs.lstat(path.join(home, ".claude", "skills", "fabric"))).isSymbolicLink()).toBe(true);
  });
});
