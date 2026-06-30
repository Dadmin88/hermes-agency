import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  HermesAgencyRosterUnavailableError,
  normalizeHermesAgencyRoster,
  readHermesAgencyRoster,
} from "../services/hermes-agency-roster.js";

const tempDirs: string[] = [];

async function tempRosterPath() {
  const dir = await mkdtemp(path.join(os.tmpdir(), "hermes-agency-roster-"));
  tempDirs.push(dir);
  return path.join(dir, "roster_state.json");
}

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

describe("Hermes Agency roster service", () => {
  it("normalizes offline and wake-failed agents without hiding them", () => {
    const roster = normalizeHermesAgencyRoster({
      profiles: [
        {
          name: "agency-backend-engineer",
          description: "Builds APIs",
          skills: ["api", "server", "api"],
          online: false,
          wake_attempt_count: 2,
          last_wake_attempt_at: "2026-06-29T10:00:00Z",
          last_wake_error: "Error: profile agency-backend-engineer not found",
          model: "gpt-5.5",
          provider: "openai-codex",
        },
        {
          name: "agency-frontend-engineer",
          capabilities: [{ id: "react" }, { id: "typescript" }],
          online: true,
        },
        {
          name: "agency-orchestrator",
          skills: ["orchestration"],
          online: true,
        },
      ],
    });

    expect(roster).toMatchObject({
      tenant: "default",
      filter: "agency-only",
      total: 3,
      online: 2,
      offline: 1,
    });
    expect(roster.agents[0]).toMatchObject({
      name: "agency-backend-engineer",
      skills: ["api", "server"],
      online: false,
      status: "wake_failed",
      wakeAttempts: 2,
      lastAttempt: "2026-06-29T10:00:00Z",
      lastError: "Error: profile agency-backend-engineer not found",
      model: "gpt-5.5",
      provider: "openai-codex",
    });
    expect(roster.agents[1]).toMatchObject({
      name: "agency-frontend-engineer",
      skills: ["react", "typescript"],
      online: true,
      status: "online",
    });
    expect(roster.agents[2]).toMatchObject({
      name: "agency-orchestrator",
      skills: ["orchestration"],
      online: true,
      status: "online",
    });
  });

  it("reads and normalizes a roster_state.json file", async () => {
    const rosterPath = await tempRosterPath();
    await writeFile(rosterPath, JSON.stringify({ profiles: [{ name: "agency-docs-writer", online: false }] }));

    await expect(readHermesAgencyRoster({ rosterPath })).resolves.toMatchObject({
      total: 1,
      online: 0,
      offline: 1,
      agents: [{ name: "agency-docs-writer", status: "offline" }],
    });
  });

  it("throws a typed unavailable error when the source is missing", async () => {
    await expect(readHermesAgencyRoster({ rosterPath: "/tmp/does-not-exist/hermes-roster.json" }))
      .rejects
      .toBeInstanceOf(HermesAgencyRosterUnavailableError);
  });
});
