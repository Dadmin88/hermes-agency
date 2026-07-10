#!/usr/bin/env python3
"""Finalize the Hermes Fabric CLI package and alias tests after bulk migration."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FABRIC = ROOT / "apps" / "fabric"

package_path = FABRIC / "cli/package.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
package["name"] = "hermes-fabric"
package["description"] = "Hermes Fabric CLI for operating the Hermes Agency frontend"
package["bin"] = {"hermes-fabric": "./dist/index.js"}
package["keywords"] = [
    keyword
    for keyword in package.get("keywords", [])
    if "paperclip" not in str(keyword).lower()
]
package["repository"] = {
    "type": "git",
    "url": "https://github.com/DeployFaith/Hermes_Agency",
    "directory": "apps/fabric/cli",
}
package["homepage"] = "https://github.com/DeployFaith/Hermes_Agency"
package["bugs"] = {"url": "https://github.com/DeployFaith/Hermes_Agency/issues"}
package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")

test_path = FABRIC / "cli/src/__tests__/package-alias.test.ts"
test_path.write_text(
    '''import fs from "node:fs";
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

describe("Hermes Fabric CLI package identity", () => {
  it("publishes only the Hermes Fabric command", () => {
    const pkg = readCliPackageJson();

    expect(pkg.name).toBe("hermes-fabric");
    expect(pkg.bin).toEqual({
      "hermes-fabric": "./dist/index.js",
    });
    expect(pkg.description).toMatch(/Hermes Fabric CLI/);
  });
});
''',
    encoding="utf-8",
)

print("Finalized Hermes Fabric CLI package identity")
