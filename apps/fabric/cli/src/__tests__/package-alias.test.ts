import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const packageJsonPath = path.resolve(__dirname, "../../package.json");

function readCliPackageJson() {
  return JSON.parse(fs.readFileSync(packageJsonPath, "utf8")) as {
    name: string;
    description?: string;
    bin?: Record<string, string>;
  };
}

describe("Hermes Fabric CLI package alias", () => {
  it("keeps paperclipai compatibility while exposing hermes-fabric", () => {
    const pkg = readCliPackageJson();

    expect(pkg.name).toBe("hermes-fabric");
    expect(pkg.bin).toEqual({
      "hermes-fabric": "./dist/index.js",
      paperclipai: "./dist/index.js",
    });
    expect(pkg.description).toMatch(/Hermes Fabric CLI/);
  });
});
