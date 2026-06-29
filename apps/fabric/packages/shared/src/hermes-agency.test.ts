import { describe, expect, it } from "vitest";
import { buildHermesAgencyTaskPacketPreview } from "./hermes-agency.js";

const baseIssue = {
  id: "issue-1",
  identifier: "HF-42",
  title: "Wire the roster page",
  description: "Build a read-only roster page for Hermes Agency specialists.",
  status: "todo",
  priority: "high",
  workMode: "standard",
  labels: [{ name: "frontend" }, { name: "react" }],
  project: { name: "Hermes Fabric", description: "Frontend for Hermes Agency" },
  goal: { title: "Make Hermes Fabric route work to Hermes Agency" },
  currentExecutionWorkspace: {
    id: "workspace-1",
    name: "Hermes_Fabric",
    rootPath: "/workspace/hermes-fabric",
    branchName: "feat/hermes-fabric-foundation",
  },
};

describe("buildHermesAgencyTaskPacketPreview", () => {
  it("builds a direct-agent packet without dispatching", () => {
    const packet = buildHermesAgencyTaskPacketPreview({
      issue: baseIssue,
      targetAgentName: "agency-frontend-engineer",
      requestedSkills: ["react", "typescript"],
      validationExpectations: ["Run targeted UI tests", "Run typecheck"],
      artifactExpectations: ["Report files changed and tests run"],
      stopConditions: ["Stop before dispatching to Hermes Agency"],
    });

    expect(packet.dispatchMode).toBe("direct-agent");
    expect(packet.targetAgentName).toBe("agency-frontend-engineer");
    expect(packet.requestedSkills).toEqual(["react", "typescript", "frontend"]);
    expect(packet.title).toBe("[HF-42] Wire the roster page");
    expect(packet.goal).toContain("Build a read-only roster page");
    expect(packet.context).toContain("Project: Hermes Fabric");
    expect(packet.context).toContain("Workspace root: /workspace/hermes-fabric");
    expect(packet.routing.rationale).toContain("Direct agent target selected");
    expect(packet.dispatchReady).toBe(false);
  });

  it("builds a skill-routed packet when no direct agent is selected", () => {
    const packet = buildHermesAgencyTaskPacketPreview({
      issue: { ...baseIssue, identifier: null, description: null },
      requestedSkills: ["backend", "api", "typescript"],
    });

    expect(packet.dispatchMode).toBe("skill-fit");
    expect(packet.targetAgentName).toBeNull();
    expect(packet.title).toBe("Wire the roster page");
    expect(packet.goal).toBe("Wire the roster page");
    expect(packet.context).toContain("Priority: high");
    expect(packet.routing.rationale).toContain("Skill-fit routing");
    expect(packet.validationExpectations).toContain("Run the smallest relevant automated check before reporting completion.");
    expect(packet.stopConditions).toContain("Stop and report if the requested work would require secrets, credentials, or destructive system changes.");
    expect(packet.dispatchReady).toBe(false);
  });

  it("deduplicates and derives skills from labels when explicit skills are omitted", () => {
    const packet = buildHermesAgencyTaskPacketPreview({
      issue: baseIssue,
      requestedSkills: ["react", "React", "  typescript  ", ""],
    });

    expect(packet.requestedSkills).toEqual(["react", "typescript", "frontend"]);
  });
});
