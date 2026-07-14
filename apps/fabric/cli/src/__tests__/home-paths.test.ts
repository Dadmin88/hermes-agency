import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  describeLocalInstancePaths,
  expandHomePrefix,
  resolveHermesFabricHomeDir,
  resolveHermesFabricInstanceId,
} from "../config/home.js";

const ORIGINAL_ENV = { ...process.env };

describe("home path resolution", () => {
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("defaults to ~/.hermes-fabric and default instance", () => {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), "fabric-home-paths-"));
    process.env.HERMES_FABRIC_HOME = home;
    delete process.env.HERMES_FABRIC_INSTANCE_ID;

    const paths = describeLocalInstancePaths();
    expect(paths.homeDir).toBe(home);
    expect(paths.instanceId).toBe("default");
    expect(paths.configPath).toBe(path.resolve(home, "instances", "default", "config.json"));
  });

  it("supports HERMES_FABRIC_HOME and explicit instance ids", () => {
    process.env.HERMES_FABRIC_HOME = "~/fabric-home";

    const home = resolveHermesFabricHomeDir();
    expect(home).toBe(path.resolve(os.homedir(), "fabric-home"));
    expect(resolveHermesFabricInstanceId("dev_1")).toBe("dev_1");
  });

  it("rejects invalid instance ids", () => {
    expect(() => resolveHermesFabricInstanceId("bad/id")).toThrow(/Invalid HERMES_FABRIC_INSTANCE_ID/);
  });

  it("expands ~ prefixes", () => {
    expect(expandHomePrefix("~")).toBe(os.homedir());
    expect(expandHomePrefix("~/x/y")).toBe(path.resolve(os.homedir(), "x/y"));
  });
});
