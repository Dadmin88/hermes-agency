import { mkdtemp, readFile, rm, stat, symlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import YAML from "yaml";
import {
  profileConfigPath,
  resolveHermesProfilesDir,
  resolveHermesProfileName,
  writeModelToProfileConfig,
} from "../services/hermes-profile-config.js";

describe("hermes profile config writer", () => {
  let tempRoot: string | null = null;

  afterEach(async () => {
    vi.unstubAllEnvs();
    if (tempRoot) {
      await rm(tempRoot, { recursive: true, force: true });
      tempRoot = null;
    }
  });

  async function makeProfilesDir() {
    tempRoot = await mkdtemp(path.join(os.tmpdir(), "hermes-profile-config-"));
    return tempRoot;
  }

  it("resolves agency profile names from agent.name", () => {
    expect(resolveHermesProfileName({ name: "agency-backend-engineer", adapterConfig: {} })).toBe(
      "agency-backend-engineer",
    );
    expect(resolveHermesProfileName({ name: "Backend", adapterConfig: { hermesProfile: "agency-ceo" } })).toBe(
      "agency-ceo",
    );
    expect(resolveHermesProfileName({ name: "Plain Agent", adapterConfig: {} })).toBeNull();
  });

  it("resolves profiles from explicit override, then HERMES_HOME", () => {
    vi.stubEnv("HERMES_HOME", "/tmp/hermes-home-for-test");
    vi.stubEnv("HERMES_PROFILES_DIR", "");
    expect(resolveHermesProfilesDir()).toBe("/tmp/hermes-home-for-test/profiles");

    vi.stubEnv("HERMES_PROFILES_DIR", "/tmp/hermes-profiles-for-test");
    expect(resolveHermesProfilesDir()).toBe("/tmp/hermes-profiles-for-test");
  });

  it("rejects traversal profile names before computing config paths", async () => {
    const profilesDir = await makeProfilesDir();
    expect(() => profileConfigPath("../outside-target", profilesDir)).toThrow(
      "Profile name must be a safe basename.",
    );
    expect(() => profileConfigPath("agency/other", profilesDir)).toThrow(
      "Profile name must be a safe basename.",
    );
  });

  it("does not write outside profilesDir for invalid profile names", async () => {
    const profilesDir = await makeProfilesDir();
    const result = await writeModelToProfileConfig({
      profileName: "../outside-target",
      provider: "openai",
      model: "gpt-5",
      modelSetName: "balanced",
      profilesDir,
    });

    expect(result).toMatchObject({
      status: "error",
      profile: "../outside-target",
      error: "Profile name must be a safe basename.",
    });
    await expect(stat(path.join(profilesDir, "..", "outside-target", "config.yaml"))).rejects.toMatchObject({
      code: "ENOENT",
    });
  });

  it("does not follow a symlinked profile directory outside profilesDir", async () => {
    const profilesDir = await makeProfilesDir();
    const outsideDir = path.join(path.dirname(profilesDir), `${path.basename(profilesDir)}-outside`);
    await import("node:fs/promises").then(({ mkdir }) => mkdir(outsideDir));
    await symlink(outsideDir, path.join(profilesDir, "agency-symlink"), "dir");

    const result = await writeModelToProfileConfig({
      profileName: "agency-symlink",
      provider: "openai",
      model: "gpt-5",
      modelSetName: "balanced",
      profilesDir,
    });

    expect(result).toMatchObject({ status: "error", profile: "agency-symlink" });
    await expect(stat(path.join(outsideDir, "config.yaml"))).rejects.toMatchObject({ code: "ENOENT" });
    await rm(outsideDir, { recursive: true, force: true });
  });

  it("creates missing config.yaml with model block", async () => {
    const profilesDir = await makeProfilesDir();
    const result = await writeModelToProfileConfig({
      profileName: "agency-test-profile",
      provider: "openai",
      model: "gpt-5",
      modelSetName: "balanced",
      family: "general_worker",
      profilesDir,
    });
    expect(result.status).toBe("updated");
    const configPath = profileConfigPath("agency-test-profile", profilesDir);
    const parsed = YAML.parse(await readFile(configPath, "utf8")) as Record<string, unknown>;
    expect(parsed.model).toMatchObject({ provider: "openai", default: "gpt-5" });
    expect(parsed.agency).toMatchObject({
      models: {
        active_set: "balanced",
        applied_family: "general_worker",
        managed_by: "hermes-fabric",
      },
    });
  });

  it("updates only the model block and preserves unrelated keys", async () => {
    const profilesDir = await makeProfilesDir();
    const configPath = profileConfigPath("agency-preserve", profilesDir);
    await import("node:fs/promises").then(({ mkdir, writeFile }) =>
      mkdir(path.dirname(configPath), { recursive: true }).then(() =>
        writeFile(
          configPath,
          YAML.stringify({
            terminal: { backend: "local" },
            model: { provider: "anthropic", default: "claude-sonnet-4" },
          }),
          "utf8",
        ),
      ),
    );

    const result = await writeModelToProfileConfig({
      profileName: "agency-preserve",
      provider: "openai",
      model: "gpt-5",
      modelSetName: "balanced",
      profilesDir,
    });
    expect(result.status).toBe("updated");
    const parsed = YAML.parse(await readFile(configPath, "utf8")) as Record<string, unknown>;
    expect(parsed.terminal).toMatchObject({ backend: "local" });
    expect(parsed.model).toMatchObject({ provider: "openai", default: "gpt-5" });
  });

  it("reports unchanged when provider/model already match", async () => {
    const profilesDir = await makeProfilesDir();
    const configPath = profileConfigPath("agency-unchanged", profilesDir);
    await import("node:fs/promises").then(({ mkdir, writeFile }) =>
      mkdir(path.dirname(configPath), { recursive: true }).then(() =>
        writeFile(
          configPath,
          YAML.stringify({ model: { provider: "openai", default: "gpt-5" } }),
          "utf8",
        ),
      ),
    );

    const result = await writeModelToProfileConfig({
      profileName: "agency-unchanged",
      provider: "openai",
      model: "gpt-5",
      modelSetName: "balanced",
      profilesDir,
    });
    expect(result.status).toBe("unchanged");
  });
});