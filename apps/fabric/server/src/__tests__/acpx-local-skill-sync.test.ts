import { describe, expect, it } from "vitest";
import {
  listAcpxSkills,
  syncAcpxSkills,
} from "@hermes-fabric/adapter-acpx-local/server";

describe("acpx local skill sync", () => {
  const fabricKey = "hermes-fabric/fabric/fabric";

  it("reports ACPX Claude skills as supported runtime-mounted state", async () => {
    const snapshot = await listAcpxSkills({
      agentId: "agent-1",
      companyId: "company-1",
      adapterType: "acpx_local",
      config: {
        agent: "claude",
        fabricSkillSync: {
          desiredSkills: [fabricKey],
        },
      },
    });

    expect(snapshot.adapterType).toBe("acpx_local");
    expect(snapshot.supported).toBe(true);
    expect(snapshot.mode).toBe("ephemeral");
    expect(snapshot.desiredSkills).toContain(fabricKey);
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.state).toBe("configured");
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.detail).toContain("ACPX Claude session");
    expect(snapshot.warnings).toEqual([]);
  });

  it("reports ACPX Codex skills with Codex home runtime detail", async () => {
    const snapshot = await syncAcpxSkills({
      agentId: "agent-2",
      companyId: "company-1",
      adapterType: "acpx_local",
      config: {
        agent: "codex",
        fabricSkillSync: {
          desiredSkills: ["fabric"],
        },
      },
    }, ["fabric"]);

    expect(snapshot.supported).toBe(true);
    expect(snapshot.mode).toBe("ephemeral");
    expect(snapshot.desiredSkills).toContain(fabricKey);
    expect(snapshot.desiredSkills).not.toContain("fabric");
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.state).toBe("configured");
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.detail).toContain("CODEX_HOME/skills/");
    expect(snapshot.warnings).toEqual([]);
  });

  it("keeps ACPX custom skill selection tracked but unsupported", async () => {
    const snapshot = await listAcpxSkills({
      agentId: "agent-3",
      companyId: "company-1",
      adapterType: "acpx_local",
      config: {
        agent: "custom",
        fabricSkillSync: {
          desiredSkills: [fabricKey],
        },
      },
    });

    expect(snapshot.supported).toBe(false);
    expect(snapshot.mode).toBe("unsupported");
    expect(snapshot.desiredSkills).toContain(fabricKey);
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.desired).toBe(true);
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.state).toBe("available");
    expect(snapshot.entries.find((entry) => entry.key === fabricKey)?.detail).toContain("stored in HermesFabric only");
    expect(snapshot.warnings).toContain(
      "Custom ACP commands do not expose a HermesFabric skill integration contract yet; selected skills are tracked only.",
    );
  });
});
