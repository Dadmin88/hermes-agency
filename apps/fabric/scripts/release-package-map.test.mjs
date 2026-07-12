import assert from "node:assert/strict";
import test from "node:test";

import {
  buildReleasePackagePlan,
  checkConfiguration,
  findUnpublishableWorkspaceEdges,
  getReleasePackages,
} from "./release-package-map.mjs";

function pkg(name, { publishFromCi, ...deps } = {}) {
  return { name, dir: name, publishFromCi, pkg: { name, ...deps } };
}

test("release package manifest covers all public packages with explicit CI enrollment", () => {
  const packages = buildReleasePackagePlan();
  assert.ok(packages.length > 0);
  assert.ok(packages.every((pkg) => typeof pkg.publishFromCi === "boolean"));
});

test("release package list only contains CI-enrolled packages", () => {
  const enabledPackages = getReleasePackages();
  assert.ok(enabledPackages.length > 0);
  assert.ok(enabledPackages.every((pkg) => pkg.publishFromCi === true));
});

test("Hermes release surface publishes the unified built-in package and keeps gateway as a shim", () => {
  const packages = buildReleasePackagePlan();
  const hermes = packages.find((pkg) => pkg.name === "@hermes-fabric/hermes-fabric-adapter");
  const gatewayShim = packages.find((pkg) => pkg.name === "@hermes-fabric/adapter-hermes-gateway");

  assert.equal(hermes?.dir, "packages/adapters/hermes");
  assert.equal(hermes?.publishFromCi, true);
  assert.equal(gatewayShim?.dir, "packages/adapters/hermes-gateway");
  assert.equal(gatewayShim?.publishFromCi, false);
});

test("release package configuration validates successfully", () => {
  assert.doesNotThrow(() => checkConfiguration());
});

test("guard flags a publishFromCi:true package depending on a publishFromCi:false package", () => {
  const problems = findUnpublishableWorkspaceEdges([
    pkg("@hermes-fabric/server", {
      publishFromCi: true,
      dependencies: { "@hermes-fabric/skills-catalog": "workspace:*" },
    }),
    pkg("@hermes-fabric/skills-catalog", { publishFromCi: false }),
  ]);

  assert.equal(problems.length, 1);
  assert.match(problems[0], /@hermes-fabric\/server/);
  assert.match(problems[0], /@hermes-fabric\/skills-catalog/);
});

test("guard inspects optional and peer dependency sections too", () => {
  const problems = findUnpublishableWorkspaceEdges([
    pkg("@hermes-fabric/server", {
      publishFromCi: true,
      optionalDependencies: { "@hermes-fabric/opt": "workspace:^" },
      peerDependencies: { "@hermes-fabric/peer": "workspace:*" },
    }),
    pkg("@hermes-fabric/opt", { publishFromCi: false }),
    pkg("@hermes-fabric/peer", { publishFromCi: false }),
  ]);

  assert.equal(problems.length, 2);
});

test("guard treats a workspace dep on an unknown @hermes-fabric package as unpublishable", () => {
  const problems = findUnpublishableWorkspaceEdges([
    pkg("@hermes-fabric/server", {
      publishFromCi: true,
      dependencies: { "@hermes-fabric/private-internal": "workspace:*" },
    }),
  ]);

  assert.equal(problems.length, 1);
});

test("guard allows true->true workspace edges", () => {
  const problems = findUnpublishableWorkspaceEdges([
    pkg("@hermes-fabric/server", {
      publishFromCi: true,
      dependencies: { "@hermes-fabric/shared": "workspace:*" },
    }),
    pkg("@hermes-fabric/shared", { publishFromCi: true }),
  ]);

  assert.deepEqual(problems, []);
});

test("guard ignores non-workspace specs, non-internal deps, and edges from off-train packages", () => {
  const problems = findUnpublishableWorkspaceEdges([
    pkg("@hermes-fabric/server", {
      publishFromCi: true,
      dependencies: {
        "@hermes-fabric/pinned": "0.3.1",
        zod: "^3.0.0",
      },
    }),
    pkg("@hermes-fabric/pinned", { publishFromCi: false }),
    pkg("@hermes-fabric/offtrain", {
      publishFromCi: false,
      dependencies: { "@hermes-fabric/also-off": "workspace:*" },
    }),
    pkg("@hermes-fabric/also-off", { publishFromCi: false }),
  ]);

  assert.deepEqual(problems, []);
});

test("the live release manifest has no unpublishable workspace edges", () => {
  assert.deepEqual(findUnpublishableWorkspaceEdges(buildReleasePackagePlan()), []);
});
